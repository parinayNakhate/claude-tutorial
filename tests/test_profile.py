"""Tests for Step 5 -- the profile page, wired to the database.

Step 4's version of this file asserted against hardcoded _PROFILE_* constants
in app.py. Those are gone: every value on the page now comes from a query
scoped to session["user_id"], so every test here seeds a real user first.

Nothing below retypes an expected number by hand. Totals, counts and the top
category are all derived from EXPENSES, so editing that constant can never
leave a test quietly asserting the wrong thing -- which was the Step 4 suite's
stated intent too, it just had a constant in app.py to lean on.
"""

import inspect
import re

import app as app_module
import database.db as db

NAME = "Grace Hopper"
EMAIL = "grace@example.com"
CREATED_AT = "2026-01-15 09:30:00"

# (date, description, category, amount) -- newest first, the order the table
# renders. Seven distinct categories across eight rows; Food is the one that
# spans two rows. Shopping is both the biggest single row and the biggest
# total here, so proving the top category is *summed* needs its own data --
# see test_the_top_category_is_summed_not_read_off_one_row.
EXPENSES = (
    ("2026-08-25", "Gift for a colleague", "Other", 500.00),
    ("2026-08-22", "Dinner with friends", "Food", 275.00),
    ("2026-08-19", "Running shoes", "Shopping", 2299.00),
    ("2026-08-16", "Movie tickets", "Entertainment", 350.00),
    ("2026-08-12", "Pharmacy - monthly medicines", "Health", 640.00),
    ("2026-08-09", "Electricity bill", "Bills", 1850.00),
    ("2026-08-06", "Metro card top-up", "Transport", 120.00),
    ("2026-08-03", "Groceries at the local market", "Food", 450.00),
)

TOTAL = sum(row[3] for row in EXPENSES)
# Derived the same way the page derives it, so the two cannot disagree.
TOP_CATEGORY = db._category_totals(
    [{"category": row[2], "amount": row[3]} for row in EXPENSES]
)[0][0]


def _seed_user(name=NAME, email=EMAIL, expenses=EXPENSES,
               created_at=CREATED_AT):
    """Create a user with expenses and return their id.

    conftest's autouse clean_tables empties both tables before every test, so
    there is never a row left over from the last one -- and never a row unless
    a test puts one there, which is why /profile now needs this.
    """
    user_id = db.create_user(name, email, "password123")
    conn = db.get_db()
    try:
        # created_at defaults to datetime('now'), so it has to be overwritten
        # to assert on a fixed "Member since" string.
        conn.execute(
            "UPDATE users SET created_at = ? WHERE id = ?",
            (created_at, user_id),
        )
        for date, description, category, amount in expenses:
            conn.execute(
                "INSERT INTO expenses "
                "(user_id, amount, category, date, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, amount, category, date, description),
            )
        conn.commit()
    finally:
        conn.close()
    return user_id


def _sign_in(client, user_id=1, user_name=NAME):
    """Put a signed-in session in the client's cookie jar without a POST.

    Same helper as tests/test_login.py: session_transaction() re-signs the
    session on exit, so the next request arrives already authenticated.
    """
    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["user_name"] = user_name


def _session(client):
    """The client's session as a plain dict."""
    with client.session_transaction() as session:
        return dict(session)


def _source(app, template):
    """The raw template source, before Jinja renders it."""
    return app.jinja_env.loader.get_source(app.jinja_env, template)[0]


def _profile(client, user_name=NAME, **seed):
    """Seed a user, sign in as them, and fetch /profile."""
    user_id = _seed_user(**seed)
    _sign_in(client, user_id=user_id, user_name=user_name)
    return client.get("/profile")


def _widths(body):
    """The bar percentages, read back out of the rendered HTML."""
    return [int(w) for w in re.findall(r'style="width: (\d+)%"', body)]


# ------------------------------------------------------------------ #
# The access gate                                                     #
# ------------------------------------------------------------------ #

def test_anonymous_visitor_is_redirected_to_login(client):
    response = client.get("/profile")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_anonymous_visitor_never_sees_the_page_body(client):
    """The redirect must not carry the content it is supposed to be gating."""
    body = client.get("/profile").data
    assert b"profile-card" not in body
    assert b"Recent transactions" not in body


def test_signed_in_visitor_gets_the_page(client):
    assert _profile(client).status_code == 200


def test_the_gate_does_not_touch_the_session(client):
    """Reading /profile must not write, clear or rotate anything."""
    user_id = _seed_user()
    _sign_in(client, user_id=user_id)
    client.get("/profile")
    assert _session(client) == {"user_id": user_id, "user_name": NAME}


def test_a_session_naming_a_deleted_user_is_cleared(client):
    """The cookie is signed, so the id is genuine -- but the row can be gone.

    Leaving the dead session in place would bounce the visitor between
    /profile and /login forever, because login() sends anyone still carrying
    a user_id straight back here.
    """
    _sign_in(client, user_id=999)
    response = client.get("/profile")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")
    assert _session(client) == {}


# ------------------------------------------------------------------ #
# Section 1 -- identity                                               #
# ------------------------------------------------------------------ #

def test_the_page_shows_the_signed_in_users_name(client):
    """The name comes from the session, not from the query."""
    body = _profile(client, user_name="Ada Lovelace").data
    assert b"Ada Lovelace" in body


def test_the_avatar_shows_the_users_initials(client):
    body = _profile(client, user_name="Ada Lovelace").data.decode()
    assert re.search(r'class="profile-avatar"[^>]*>\s*AL\s*<', body)


def test_a_single_word_name_does_not_break_the_avatar(client):
    """parts[-1][0] would still work, but parts[0][0] is the whole name."""
    response = _profile(client, user_name="Ada")
    assert response.status_code == 200
    assert re.search(
        r'class="profile-avatar"[^>]*>\s*A\s*<', response.data.decode()
    )


def test_an_empty_name_falls_back_instead_of_raising(client):
    """A session can carry an empty name; a 500 here would be absurd."""
    response = _profile(client, user_name="")
    assert response.status_code == 200
    assert re.search(
        r'class="profile-avatar"[^>]*>\s*\?\s*<', response.data.decode()
    )


def test_the_page_shows_the_stored_email(client):
    body = _profile(client).data
    assert EMAIL.encode() in body


def test_the_join_date_is_formatted_not_dumped(client):
    """created_at carries a time; only the month and year should surface."""
    body = _profile(client).data.decode()
    assert "Member since January 2026" in body
    assert "09:30" not in body
    assert "2026-01-15" not in body


# ------------------------------------------------------------------ #
# Section 2 -- summary stats                                          #
# ------------------------------------------------------------------ #

def test_all_three_summary_stats_render(client):
    body = _profile(client).data
    for label in (b"Total spent", b"Transactions", b"Top category"):
        assert label in body


def test_the_total_is_formatted_as_rupees_with_separators(client):
    body = _profile(client).data.decode()
    assert app_module.rupees(TOTAL) in body


def test_the_transaction_count_matches_the_data(client):
    body = _profile(client).data.decode()
    assert re.search(
        r'profile-stat-value">\s*%d\s*<' % len(EXPENSES), body
    )


def test_the_top_category_renders(client):
    body = _profile(client).data.decode()
    assert re.search(r'profile-stat-value">\s*%s\s*<' % TOP_CATEGORY, body)


def test_the_top_category_is_summed_not_read_off_one_row(client):
    """Food wins on two rows of 300; Bills has the largest single row.

    EXPENSES cannot make this point -- Shopping is both its biggest single
    row and its biggest total, so either strategy would look right. This
    needs data where the two answers disagree.
    """
    split = (
        ("2026-05-03", "a", "Food", 300.00),
        ("2026-05-02", "b", "Food", 300.00),
        ("2026-05-01", "c", "Bills", 500.00),
    )
    user_id = _seed_user(expenses=split)
    _sign_in(client, user_id=user_id)
    body = client.get("/profile").data.decode()
    assert re.search(r'profile-stat-value">\s*Food\s*<', body)
    assert not re.search(r'profile-stat-value">\s*Bills\s*<', body)


# ------------------------------------------------------------------ #
# Section 3 -- transaction history                                    #
# ------------------------------------------------------------------ #

def test_every_transaction_gets_a_row(client):
    body = _profile(client).data.decode()
    assert len(re.findall(r"<time datetime=", body)) == len(EXPENSES)


def test_each_row_carries_its_description_and_amount(client):
    body = _profile(client).data.decode()
    for _, description, _, amount in EXPENSES:
        assert description in body
        assert app_module.rupees(amount) in body


def test_the_rows_are_ordered_newest_first(client):
    body = _profile(client).data.decode()
    positions = [body.index(row[1]) for row in EXPENSES]
    assert positions == sorted(positions)


def test_rows_sharing_a_date_keep_a_stable_order(client):
    """date has no time component, so ties need id DESC to stay put.

    Without the tiebreaker SQLite may return equal dates in any order and the
    table would reshuffle between two renders of identical data.
    """
    same_day = (
        ("2026-05-01", "inserted first", "Food", 10.00),
        ("2026-05-01", "inserted second", "Food", 20.00),
    )
    user_id = _seed_user(expenses=same_day)
    rows = db.get_recent_transactions(user_id)
    assert [row["description"] for row in rows] == [
        "inserted second", "inserted first"
    ]


def test_category_badges_use_a_class_never_an_inline_colour(client):
    body = _profile(client).data.decode()
    badges = re.findall(r'class="profile-badge[^"]*"', body)
    assert badges
    assert not re.search(r'class="profile-badge[^"]*"[^>]*style=', body)


def test_badge_modifiers_match_the_categories_in_the_data(client):
    body = _profile(client).data.decode()
    for _, _, category, _ in EXPENSES:
        assert "profile-badge-%s" % category.lower() in body


def test_a_missing_description_renders_blank_not_the_word_none(client):
    """description is nullable, and Jinja prints None as the literal "None"."""
    user_id = _seed_user(expenses=(("2026-05-01", None, "Food", 10.00),))
    _sign_in(client, user_id=user_id)
    body = client.get("/profile").data.decode()
    assert ">None<" not in body


# ------------------------------------------------------------------ #
# Section 4 -- category breakdown                                     #
# ------------------------------------------------------------------ #

def test_every_category_gets_a_bar(client):
    body = _profile(client).data.decode()
    categories = set(row[2] for row in EXPENSES)
    assert len(_widths(body)) == len(categories)


def test_the_bar_percentages_cover_the_whole_total(client):
    assert sum(_widths(_profile(client).data.decode())) == 100


def test_the_bars_are_ordered_largest_first(client):
    widths = _widths(_profile(client).data.decode())
    assert widths == sorted(widths, reverse=True)


def test_each_bar_is_labelled_for_screen_readers(client):
    body = _profile(client).data.decode()
    categories = set(row[2] for row in EXPENSES)
    assert len(re.findall(r"aria-label=", body)) >= len(categories)


def test_the_breakdown_totals_match_the_transactions(client):
    user_id = _seed_user()
    breakdown = db.get_category_breakdown(user_id)
    assert sum(row["amount"] for row in breakdown) == TOTAL


def test_percentages_still_sum_to_100_when_rounding_fights_back(client):
    """40.5 / 40.5 / 19 is the case that breaks naive per-bar rounding.

    Rounding each independently gives 41 / 41 / 19 = 101, and docking the
    largest to compensate leaves 40 / 41 / 19 -- a chart that no longer
    descends even though the amounts still do.
    """
    awkward = (
        ("2026-05-03", "a", "Food", 40.50),
        ("2026-05-02", "b", "Bills", 40.50),
        ("2026-05-01", "c", "Other", 19.00),
    )
    rows = db.get_category_breakdown(_seed_user(expenses=awkward))
    percents = [row["percent"] for row in rows]
    assert sum(percents) == 100
    assert percents == sorted(percents, reverse=True)


def test_three_equal_categories_still_sum_to_100(client):
    equal = (
        ("2026-05-03", "a", "Food", 1.00),
        ("2026-05-02", "b", "Bills", 1.00),
        ("2026-05-01", "c", "Other", 1.00),
    )
    rows = db.get_category_breakdown(_seed_user(expenses=equal))
    assert sum(row["percent"] for row in rows) == 100


# ------------------------------------------------------------------ #
# One account never sees another's money                              #
# ------------------------------------------------------------------ #

def test_a_user_sees_only_their_own_transactions(client):
    """Nothing before Step 5 covered the WHERE user_id = ? clause."""
    mine = _seed_user(email="mine@example.com", expenses=(
        ("2026-05-01", "my own dinner", "Food", 10.00),
    ))
    _seed_user(email="theirs@example.com", expenses=(
        ("2026-06-01", "somebody elses yacht", "Other", 99999.00),
    ))
    _sign_in(client, user_id=mine)
    body = client.get("/profile").data.decode()
    assert "my own dinner" in body
    assert "somebody elses yacht" not in body
    assert app_module.rupees(10.00) in body
    assert "99,999" not in body


def test_the_identity_header_belongs_to_the_signed_in_user(client):
    """The transactions being scoped is no help if the header leaks."""
    _seed_user(email="first@example.com", created_at="2020-02-02 00:00:00",
               expenses=())
    second = _seed_user(email="second@example.com",
                        created_at="2026-01-15 09:30:00", expenses=())
    _sign_in(client, user_id=second)
    body = client.get("/profile").data.decode()
    assert "second@example.com" in body
    assert "first@example.com" not in body
    assert "Member since January 2026" in body
    assert "February 2020" not in body


def test_the_isolation_is_not_just_first_user_wins(client):
    """The mirror of the test above, so a 'return user 1' bug cannot pass."""
    _seed_user(email="first@example.com", expenses=(
        ("2026-05-01", "the first users lunch", "Food", 10.00),
    ))
    second = _seed_user(email="second@example.com", expenses=(
        ("2026-06-01", "the second users taxi", "Transport", 20.00),
    ))
    _sign_in(client, user_id=second)
    body = client.get("/profile").data.decode()
    assert "the second users taxi" in body
    assert "the first users lunch" not in body


# ------------------------------------------------------------------ #
# Empty states -- reachable now, for any brand-new account            #
# ------------------------------------------------------------------ #

def test_a_new_account_gets_the_empty_states_not_an_error(client):
    user_id = _seed_user(expenses=())
    _sign_in(client, user_id=user_id)
    response = client.get("/profile")
    assert response.status_code == 200
    body = response.data.decode()
    assert "No transactions yet." in body
    assert "Nothing to break down yet." in body
    assert app_module.rupees(0) in body


def test_the_empty_summary_reports_zeros_and_a_dash(client):
    stats = db.get_summary_stats(_seed_user(expenses=()))
    assert stats == {"total": 0, "count": 0, "top_category": "—"}


# ------------------------------------------------------------------ #
# Money is rupees                                                     #
# ------------------------------------------------------------------ #

def test_the_rupees_filter_formats_with_separators_and_paise():
    assert app_module.rupees(6484.0) == "₹6,484.00"
    assert app_module.rupees(0) == "₹0.00"
    assert app_module.rupees(120.5) == "₹120.50"


def test_no_dollar_signs_reach_the_page(client):
    assert b"$" not in _profile(client).data


def test_the_query_layer_never_formats_currency(client):
    """The rupees filter owns the symbol; a formatted string would break it."""
    user_id = _seed_user()
    stats = db.get_summary_stats(user_id)
    assert not isinstance(stats["total"], str)
    for row in db.get_recent_transactions(user_id):
        assert not isinstance(row["amount"], str)
    for row in db.get_category_breakdown(user_id):
        assert not isinstance(row["amount"], str)


# ------------------------------------------------------------------ #
# Dates                                                               #
# ------------------------------------------------------------------ #

def test_the_day_filter_formats_stored_dates_for_humans():
    assert app_module.day("2026-08-25") == "25 Aug 2026"
    assert app_module.day("2026-08-03") == "3 Aug 2026"


def test_the_day_filter_falls_back_instead_of_raising():
    """A malformed date should spoil one cell, not the whole render."""
    assert app_module.day("not-a-date") == "not-a-date"
    assert app_module.day(None) is None


def test_the_member_since_helper_handles_both_stored_shapes():
    """datetime('now') writes a timestamp; a fixture may write a bare date."""
    assert app_module._member_since("2026-01-15 09:30:00") == "January 2026"
    assert app_module._member_since("2026-01-15") == "January 2026"
    assert app_module._member_since("garbage") == "garbage"
    assert app_module._member_since(None) is None


def test_the_table_shows_readable_dates_not_raw_timestamps(client):
    body = _profile(client).data.decode()
    newest = EXPENSES[0][0]
    assert app_module.day(newest) in body
    # The ISO form survives only in the machine-readable attribute.
    assert ">%s<" % newest not in body
    assert 'datetime="%s"' % newest in body


# ------------------------------------------------------------------ #
# House rules                                                         #
# ------------------------------------------------------------------ #

def test_profile_contains_no_sql(client):
    """CLAUDE.md: DB logic belongs in database/db.py, never in a route."""
    source = inspect.getsource(app_module.profile)
    for token in ("SELECT", "INSERT", "UPDATE", "DELETE", "get_db("):
        assert token not in source


def test_no_helper_in_app_reaches_for_the_database(client):
    """The view's helpers must stay presentation-only too."""
    source = inspect.getsource(app_module._member_since)
    for token in ("SELECT", "INSERT", "UPDATE", "DELETE", "get_db("):
        assert token not in source


def test_the_step_four_constants_are_gone(client):
    """A bad merge that resurrects the hardcoded block should fail loudly."""
    assert not [n for n in dir(app_module) if n.startswith("_PROFILE_")]


def test_every_section_is_actually_wired_up(client):
    """One section left stubbed would still render a plausible-looking page."""
    body = _profile(client).data.decode()
    assert len(re.findall(r"<time datetime=", body)) == len(EXPENSES)
    assert app_module.rupees(TOTAL) in body
    assert len(_widths(body)) == len(set(row[2] for row in EXPENSES))


def test_profile_template_has_no_hardcoded_urls(client, app):
    source = _source(app, "profile.html")
    assert 'href="/' not in source
    assert "url_for(" in source


def test_profile_template_has_no_hex_colours(client, app):
    """CLAUDE.md: use CSS variables, never hardcode hex values."""
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", _source(app, "profile.html"))


def test_profile_template_extends_base(client, app):
    assert '{% extends "base.html" %}' in _source(app, "profile.html")


def test_profile_css_is_page_scoped_not_global(client, app):
    """The stylesheet loads from profile.html, so no other page pays for it."""
    assert "css/profile.css" in _source(app, "profile.html")
    assert "css/profile.css" not in _source(app, "base.html")


def test_profile_page_has_no_inline_style_block(client, app):
    """Page styles belong in a .css file, not a <style> tag."""
    assert "<style" not in _source(app, "profile.html")


def test_the_only_inline_styles_are_bar_widths(client):
    """Width is data. Everything else must come from a class."""
    body = _profile(client).data.decode()
    for value in re.findall(r'style="([^"]*)"', body):
        assert re.match(r"^width: \d+%$", value), value


# ------------------------------------------------------------------ #
# Navigation                                                          #
# ------------------------------------------------------------------ #

def test_the_nav_greeting_links_to_the_profile(client):
    """Without this the page is unreachable except by typing the URL."""
    _sign_in(client)
    body = client.get("/").data.decode()
    assert re.search(r'<a href="/profile" class="nav-user">', body)


def test_the_nav_still_shows_the_signed_in_state_on_the_profile(client):
    body = _profile(client).data
    assert b"nav-user" in body
    assert b"Sign out" in body
    assert b"Get started" not in body


def test_the_mobile_nav_rule_does_not_hide_the_greeting(client):
    """.nav-user became an <a> in Step 4; the 600px rule must exempt it."""
    with open("static/css/style.css") as handle:
        css = handle.read()
    assert ".nav-links a:not(.nav-cta):not(.nav-signout):not(.nav-user)" in css


# ------------------------------------------------------------------ #
# Nothing else moved                                                  #
# ------------------------------------------------------------------ #

def test_profile_no_longer_returns_a_raw_string(client):
    """CLAUDE.md: no raw string returns once a step is implemented."""
    response = _profile(client)
    assert response.status_code == 200
    assert b"coming in Step 4" not in response.data
    assert b"<!DOCTYPE html>" in response.data


def test_the_expense_stubs_are_untouched(client):
    expected = {
        # /expenses/add left this table in Step 7, when it became a real
        # route. Its replacement coverage lives in test_add_expense.py.
        "/expenses/1/edit": "Edit expense — coming in Step 8",
        "/expenses/1/delete": "Delete expense — coming in Step 9",
    }
    for path, body in expected.items():
        response = client.get(path)
        assert response.status_code == 200
        assert response.data.decode() == body
