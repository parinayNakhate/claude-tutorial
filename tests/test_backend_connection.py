"""Unit tests for Step 5 -- the query helpers behind /profile.

tests/test_profile.py drives these through a rendered page. This file calls
them directly, so a failure points at one function instead of at a wall of
HTML, and so each helper is pinned independently of the other three.

Key names here are the template's -- `total`, `count`, `category`, `percent`.
The Step 5 spec sketched `total_spent` / `transaction_count` / `pct` for a
`database/queries.py` module that CLAUDE.md does not allow; the helpers live
in database/db.py and return what templates/profile.html actually reads.
"""

import database.db as db

NAME = "Grace Hopper"


def _user(email="grace@example.com", name=NAME,
          created_at="2026-01-15 09:30:00"):
    """Create a user and return their id."""
    user_id = db.create_user(name, email, "password123")
    conn = db.get_db()
    try:
        conn.execute(
            "UPDATE users SET created_at = ? WHERE id = ?",
            (created_at, user_id),
        )
        conn.commit()
    finally:
        conn.close()
    return user_id


def _spend(user_id, rows):
    """Insert (date, description, category, amount) rows for a user."""
    conn = db.get_db()
    try:
        for date, description, category, amount in rows:
            conn.execute(
                "INSERT INTO expenses "
                "(user_id, amount, category, date, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, amount, category, date, description),
            )
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# get_user_by_id                                                      #
# ------------------------------------------------------------------ #

def test_get_user_by_id_returns_the_matching_row():
    user_id = _user()
    row = db.get_user_by_id(user_id)
    assert row["id"] == user_id
    assert row["name"] == NAME
    assert row["email"] == "grace@example.com"
    assert row["created_at"] == "2026-01-15 09:30:00"


def test_get_user_by_id_is_scoped_to_the_id_it_is_given():
    """With one row in the table, "the match" and "the first row" look alike.

    clean_tables empties users before every test, so a helper that ignored
    its argument entirely would satisfy the test above. Two users make the
    difference visible -- and a leak here would print somebody else's email
    and join date at the top of their profile.
    """
    first = _user(email="first@example.com", name="First Person")
    second = _user(email="second@example.com", name="Second Person")
    assert db.get_user_by_id(second)["email"] == "second@example.com"
    assert db.get_user_by_id(second)["name"] == "Second Person"
    assert db.get_user_by_id(first)["email"] == "first@example.com"


def test_get_user_by_id_returns_none_for_a_missing_row():
    """A signed cookie can outlive the account it names."""
    assert db.get_user_by_id(9999) is None


def test_get_user_by_id_does_not_read_the_password_hash():
    """A hash that never leaves db.py cannot reach a template context."""
    row = db.get_user_by_id(_user())
    assert "password_hash" not in row.keys()


# ------------------------------------------------------------------ #
# get_recent_transactions                                             #
# ------------------------------------------------------------------ #

def test_recent_transactions_are_newest_first():
    user_id = _user()
    _spend(user_id, (
        ("2026-01-01", "oldest", "Food", 10.00),
        ("2026-03-01", "newest", "Bills", 30.00),
        ("2026-02-01", "middle", "Other", 20.00),
    ))
    rows = db.get_recent_transactions(user_id)
    assert [r["description"] for r in rows] == ["newest", "middle", "oldest"]


def test_recent_transactions_break_date_ties_by_insertion_order():
    """Dates carry no time, so ties are routine and must not reshuffle."""
    user_id = _user()
    _spend(user_id, (
        ("2026-03-01", "first", "Food", 10.00),
        ("2026-03-01", "second", "Food", 20.00),
    ))
    rows = db.get_recent_transactions(user_id)
    assert [r["description"] for r in rows] == ["second", "first"]


def test_recent_transactions_carry_exactly_the_keys_the_template_reads():
    user_id = _user()
    _spend(user_id, (("2026-03-01", "lunch", "Food", 10.00),))
    row = db.get_recent_transactions(user_id)[0]
    assert set(row) == {"date", "description", "category", "amount"}
    assert row["date"] == "2026-03-01"


def test_a_null_description_becomes_an_empty_string():
    """Jinja renders a None as the literal word "None" into a table cell."""
    user_id = _user()
    _spend(user_id, (("2026-03-01", None, "Food", 10.00),))
    assert db.get_recent_transactions(user_id)[0]["description"] == ""


def test_recent_transactions_are_scoped_to_one_user():
    mine = _user(email="mine@example.com")
    theirs = _user(email="theirs@example.com")
    _spend(mine, (("2026-03-01", "mine", "Food", 10.00),))
    _spend(theirs, (("2026-03-02", "theirs", "Food", 20.00),))
    rows = db.get_recent_transactions(mine)
    assert [r["description"] for r in rows] == ["mine"]


def test_recent_transactions_respect_the_limit():
    user_id = _user()
    _spend(user_id, tuple(
        ("2026-03-%02d" % day, "row %d" % day, "Food", 10.00)
        for day in range(1, 13)
    ))
    assert len(db.get_recent_transactions(user_id)) == 10
    assert len(db.get_recent_transactions(user_id, limit=3)) == 3


def test_recent_transactions_are_empty_for_a_new_account():
    assert db.get_recent_transactions(_user()) == []


# ------------------------------------------------------------------ #
# get_summary_stats                                                   #
# ------------------------------------------------------------------ #

def test_summary_stats_total_and_count():
    user_id = _user()
    _spend(user_id, (
        ("2026-03-01", "a", "Food", 100.00),
        ("2026-03-02", "b", "Bills", 50.00),
    ))
    stats = db.get_summary_stats(user_id)
    assert set(stats) == {"total", "count", "top_category"}
    assert stats["total"] == 150.00
    assert stats["count"] == 2


def test_the_top_category_is_summed_not_the_biggest_single_row():
    """Food wins on two rows of 100; Bills has the largest single row."""
    user_id = _user()
    _spend(user_id, (
        ("2026-03-01", "a", "Food", 100.00),
        ("2026-03-02", "b", "Food", 100.00),
        ("2026-03-03", "c", "Bills", 150.00),
    ))
    assert db.get_summary_stats(user_id)["top_category"] == "Food"


def test_summary_stats_are_scoped_to_one_user():
    mine = _user(email="mine@example.com")
    theirs = _user(email="theirs@example.com")
    _spend(mine, (("2026-03-01", "mine", "Food", 10.00),))
    _spend(theirs, (("2026-03-02", "theirs", "Bills", 9999.00),))
    assert db.get_summary_stats(mine)["total"] == 10.00


def test_summary_stats_for_a_new_account_are_zeros_and_a_dash():
    """A brand-new user landing here is the normal first experience."""
    assert db.get_summary_stats(_user()) == {
        "total": 0, "count": 0, "top_category": "—",
    }


# ------------------------------------------------------------------ #
# get_category_breakdown                                              #
# ------------------------------------------------------------------ #

def test_the_breakdown_is_ordered_largest_first():
    user_id = _user()
    _spend(user_id, (
        ("2026-03-01", "a", "Food", 50.00),
        ("2026-03-02", "b", "Bills", 100.00),
        ("2026-03-03", "c", "Other", 25.00),
    ))
    rows = db.get_category_breakdown(user_id)
    assert [r["category"] for r in rows] == ["Bills", "Food", "Other"]
    assert set(rows[0]) == {"category", "amount", "percent"}


def test_breakdown_amounts_are_summed_per_category():
    user_id = _user()
    _spend(user_id, (
        ("2026-03-01", "a", "Food", 30.00),
        ("2026-03-02", "b", "Food", 20.00),
    ))
    rows = db.get_category_breakdown(user_id)
    assert len(rows) == 1
    assert rows[0]["amount"] == 50.00


def test_percentages_are_whole_numbers_summing_to_100():
    user_id = _user()
    _spend(user_id, (
        ("2026-03-01", "a", "Food", 100.00),
        ("2026-03-02", "b", "Bills", 50.00),
        ("2026-03-03", "c", "Other", 25.00),
    ))
    rows = db.get_category_breakdown(user_id)
    assert all(isinstance(r["percent"], int) for r in rows)
    assert sum(r["percent"] for r in rows) == 100


def test_percentages_stay_ordered_when_rounding_fights_back():
    """41 / 41 / 19 = 101; docking the leader would give 40 / 41 / 19."""
    user_id = _user()
    _spend(user_id, (
        ("2026-03-01", "a", "Food", 40.50),
        ("2026-03-02", "b", "Bills", 40.50),
        ("2026-03-03", "c", "Other", 19.00),
    ))
    percents = [r["percent"] for r in db.get_category_breakdown(user_id)]
    assert sum(percents) == 100
    assert percents == sorted(percents, reverse=True)


def test_three_equal_categories_still_sum_to_100():
    user_id = _user()
    _spend(user_id, (
        ("2026-03-01", "a", "Food", 1.00),
        ("2026-03-02", "b", "Bills", 1.00),
        ("2026-03-03", "c", "Other", 1.00),
    ))
    percents = [r["percent"] for r in db.get_category_breakdown(user_id)]
    assert sum(percents) == 100
    assert percents == sorted(percents, reverse=True)


def test_a_zero_total_does_not_divide_by_zero():
    """Every amount can legitimately be zero; a 500 here would be absurd."""
    user_id = _user()
    _spend(user_id, (
        ("2026-03-01", "a", "Food", 0.00),
        ("2026-03-02", "b", "Bills", 0.00),
    ))
    rows = db.get_category_breakdown(user_id)
    assert all(r["percent"] == 0 for r in rows)


def test_the_breakdown_is_scoped_to_one_user():
    mine = _user(email="mine@example.com")
    theirs = _user(email="theirs@example.com")
    _spend(mine, (("2026-03-01", "mine", "Food", 10.00),))
    _spend(theirs, (("2026-03-02", "theirs", "Bills", 9999.00),))
    rows = db.get_category_breakdown(mine)
    assert [r["category"] for r in rows] == ["Food"]


def test_the_breakdown_is_empty_for_a_new_account():
    assert db.get_category_breakdown(_user()) == []
