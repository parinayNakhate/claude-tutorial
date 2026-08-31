"""SQLite helpers for Spendly.

get_db()            -- connection with dict-like rows and foreign key enforcement on
init_db()           -- create all tables (safe to call repeatedly)
seed_db()           -- insert demo data exactly once (safe to call repeatedly)
get_user_by_email() -- look up a single user by their normalised email
get_user_by_id()    -- look up a single user by their primary key
create_user()       -- hash a password and insert a new user
insert_expense()    -- insert one expense row for a user (Step 7)

Profile page queries, one per section (Step 5):

get_recent_transactions() -- one user's expenses, newest first
get_summary_stats()       -- one user's total, transaction count and top category
get_category_breakdown()  -- one user's spending per category, largest first

All three take the same optional inclusive start/end date bounds (Step 6),
built by the shared private _date_clause(). Omitting both means all time and
emits the query each one emitted before those arguments existed, byte for byte.
"""

import calendar
import os
import sqlite3
from datetime import date

from werkzeug.security import generate_password_hash

# db.py lives in <project_root>/database/, so climb one level to reach the root.
# Resolved from __file__ rather than the cwd so the path holds no matter where
# the app or a script is launched from.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "spendly.db")

# Fixed category list. Kept here so later steps can import it.
CATEGORIES = (
    "Food",
    "Transport",
    "Bills",
    "Health",
    "Entertainment",
    "Shopping",
    "Other",
)

# Development seed credentials only -- never a real account.
DEMO_NAME = "Demo User"
DEMO_EMAIL = "demo@spendly.com"
DEMO_PASSWORD = "demo123"

# Werkzeug 3.x defaults to scrypt, which this Python build's hashlib was not
# compiled with. pbkdf2 is supported everywhere and needs no extra packages.
PASSWORD_HASH_METHOD = "pbkdf2:sha256"

# SQLite needs the parenthesised form for a function default --
# a bare DEFAULT datetime('now') is a syntax error.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS expenses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    amount      REAL    NOT NULL,
    category    TEXT    NOT NULL,
    date        TEXT    NOT NULL,
    description TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);
"""

# (amount, category, description) -- dates are assigned at seed time.
_SEED_EXPENSES = (
    (450.00, "Food", "Groceries at the local market"),
    (120.00, "Transport", "Metro card top-up"),
    (1850.00, "Bills", "Electricity bill"),
    (640.00, "Health", "Pharmacy - monthly medicines"),
    (350.00, "Entertainment", "Movie tickets"),
    (2299.00, "Shopping", "Running shoes"),
    (275.00, "Food", "Dinner with friends"),
    (500.00, "Other", "Gift for a colleague"),
)


def get_db():
    """Return a new SQLite connection to the project-root database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Foreign keys are off by default and the pragma is per-connection. It is
    # also a silent no-op inside an open transaction, so set it immediately.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create all tables if they do not already exist."""
    conn = get_db()
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _seed_dates(count):
    """Return `count` distinct YYYY-MM-DD strings across the current month.

    Dates are spread over days 1..today so demo data never lands in the
    future. Early in the month there are not enough elapsed days to give each
    expense its own date, so we widen to the full month rather than pile every
    row onto the same day -- a spread of dates matters more to the demo than
    avoiding a few future ones.
    """
    today = date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    span = today.day if today.day >= count else last_day
    return [
        "{:04d}-{:02d}-{:02d}".format(
            today.year, today.month, max(1, int(round(i * span / count)))
        )
        for i in range(1, count + 1)
    ]


def seed_db():
    """Insert the demo user and sample expenses -- only if the DB is empty."""
    conn = get_db()
    try:
        # Bail out if the users table already holds data, so repeated calls
        # (the debug reloader imports app.py twice) never duplicate rows.
        if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None:
            return

        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (
                DEMO_NAME,
                DEMO_EMAIL,
                generate_password_hash(DEMO_PASSWORD, method=PASSWORD_HASH_METHOD),
            ),
        )
        user_id = cur.lastrowid

        dates = _seed_dates(len(_SEED_EXPENSES))
        rows = [
            (user_id, amount, category, day, description)
            for (amount, category, description), day in zip(_SEED_EXPENSES, dates)
        ]
        conn.executemany(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def get_user_by_email(email):
    """Return the users row matching `email`, or None if there is no match.

    The caller normalises the address with .strip().lower() before calling.
    The UNIQUE index on users.email has no COLLATE NOCASE, so this comparison
    is case-sensitive and only matches the exact form that was stored.
    """
    conn = get_db()
    try:
        # fetchone() runs inside the try so the row is materialised while the
        # connection is open. sqlite3.Row holds plain values, so it stays
        # readable after close().
        return conn.execute(
            "SELECT id, name, email, password_hash, created_at "
            "FROM users WHERE email = ?",
            (email,),
        ).fetchone()
    finally:
        conn.close()


def get_user_by_id(user_id):
    """Return the users row matching `user_id`, or None if there is no match.

    `user_id` comes from session["user_id"]. That cookie is signed, so the
    value is genuine -- but genuine is not the same as current: an account
    removed while its owner was still signed in leaves a valid cookie
    pointing at a row that is gone. None is an ordinary answer here, not an
    error, and every caller has to handle it.

    password_hash is deliberately not read. Only login() needs it, and a hash
    that never leaves this module cannot end up in a template context.
    """
    conn = get_db()
    try:
        # fetchone() inside the try for the same reason as get_user_by_email():
        # the row is materialised while the connection is still open.
        return conn.execute(
            "SELECT id, name, email, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()


def create_user(name, email, password):
    """Insert a new user and return the new row's id.

    `password` arrives in plain text and is hashed here with
    PASSWORD_HASH_METHOD, mirroring seed_db(), so no caller handles a raw hash.
    `email` must already be normalised by the caller.

    Raises sqlite3.IntegrityError if the email is taken. That is deliberate:
    a check-then-insert in the caller is a race, so the UNIQUE constraint is
    the real guard and the caller must handle it.
    """
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (
                name,
                email,
                generate_password_hash(password, method=PASSWORD_HASH_METHOD),
            ),
        )
        # Without this the implicit transaction is discarded by close() and
        # the insert is silently lost.
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def insert_expense(user_id, amount, category, date, description=None):
    """Insert one expense for `user_id` and return the new row's id.

    Mirrors create_user(): the caller has already validated and normalised
    every value, so nothing is re-checked here. `amount` is a plain number --
    the query layer never formats currency, the `rupees` filter in app.py owns
    the symbol -- and `date` is a zero-padded "YYYY-MM-DD" string, the only
    form get_recent_transactions() can order by and _date_clause() can compare
    against.

    `description` is nullable and defaults to None, which is what a blank box
    on the form means. get_recent_transactions() already squashes that back to
    "" for display, so no template has to.

    `id` and `created_at` are left to the schema: AUTOINCREMENT and
    datetime('now') respectively.

    Raises sqlite3.IntegrityError if `user_id` names no row -- get_db() turns
    foreign keys on, so that constraint is live rather than decorative.
    """
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO expenses "
            "(user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, category, date, description),
        )
        # Without this the implicit transaction is discarded by close() and
        # the row is silently lost -- the same trap create_user() documents.
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Profile page queries -- Steps 5-6                                   #
# ------------------------------------------------------------------ #

# One helper per section of /profile. They are deliberately independent --
# none of them takes another's output -- so each can be read, tested and
# changed on its own and the view assembles the page from three plain calls.


def _category_totals(rows):
    """Return (category, total) pairs, largest first.

    A plain dict would order by insertion in 3.7+, but the bars need to be
    sorted by size anyway, so the sort is doing the real work here.

    Shared by the summary and the breakdown, which is why it sits above both
    rather than inside either one: two copies could drift and leave the
    headline "top category" naming a different bar than the chart shows.

    Rows subscript by column name exactly like dicts, so this works on
    sqlite3.Row and on hand-written dicts in tests without a branch.
    """
    totals = {}
    for row in rows:
        totals[row["category"]] = totals.get(row["category"], 0) + row["amount"]
    return sorted(totals.items(), key=lambda pair: pair[1], reverse=True)


def _date_clause(start, end):
    """Return the SQL and parameters for an optional date window.

    Gives back a (sql, params) pair: `sql` is a fragment to append directly
    after "WHERE user_id = ?" -- it opens with its own space and ends without
    one -- and `params` are the values filling its placeholders, in the same
    order, ready to concatenate into the caller's tuple.

    With neither bound it returns ("", ()), so each query below emits the exact
    string and the exact tuple it emitted before these arguments existed. That
    is the whole contract: /profile with no query string is all time and must
    stay untouched, and several Step 5 tests count rows and bars against the
    full seeded set.

    Both bounds are inclusive -- someone asking for 1 to 31 August means the
    31st too. expenses.date is TEXT in zero-padded YYYY-MM-DD, which sorts
    lexicographically in the same order it sorts chronologically, so plain
    string comparison is the correct comparison and no date() conversion is
    needed on either side of the operator.

    Shared by all three queries rather than written out in each, for the same
    reason _category_totals() is shared: three copies of one clause can drift,
    and a page whose bars cover a different window than its headline total is
    worse than a page that cannot filter at all.

    A falsy bound -- None or "" -- means no bound on that side, so a caller
    handing an empty form field straight through gets the unfiltered query
    rather than one that matches nothing.
    """
    sql = ""
    params = ()
    if start:
        sql += " AND date >= ?"
        params += (start,)
    if end:
        sql += " AND date <= ?"
        params += (end,)
    return sql, params


def get_recent_transactions(user_id, limit=10, start=None, end=None):
    """Return `user_id`'s most recent expenses, newest first.

    One dict per expense with exactly the four keys profile.html reads:
    `date` (the stored YYYY-MM-DD string, handed straight to the `day`
    filter), `description`, `category` and `amount` (a number -- the `rupees`
    filter adds the symbol, so nothing here formats currency).

    Returns [] for a user with no expenses; the template's {% else %} branch
    renders the empty state.

    `start` and `end` are optional inclusive YYYY-MM-DD bounds. They narrow
    which rows are eligible; they do not change the ordering. The caller
    validates them -- this layer only binds them.

    A `limit` of None lifts the cap entirely. /profile passes None once a
    window is active: a table capped at ten rows underneath a headline
    counting every row in the window is a page arguing with itself, and a
    window the visitor drew themselves is already bounded.
    """
    clause, date_params = _date_clause(start, end)
    # date is a bare YYYY-MM-DD string with no time component, so several rows
    # routinely share a day. id DESC breaks those ties by insertion order --
    # without it SQLite may hand back equal dates in any order and the table
    # would reshuffle itself between two renders of identical data.
    sql = (
        "SELECT id, amount, category, date, description "
        "FROM expenses WHERE user_id = ?"
        + clause
        + " ORDER BY date DESC, id DESC"
    )
    params = (user_id,) + date_params
    if limit is not None:
        sql += " LIMIT ?"
        params += (limit,)

    conn = get_db()
    try:
        rows = conn.execute(sql, params).fetchall()
        # Built inside the try for the same reason as get_user_by_email():
        # the rows are materialised while the connection is still open.
        # description is nullable, and a None would reach Jinja and print the
        # literal word "None" into a cell for the user to read, so it is
        # squashed to "" here rather than in every template that shows it.
        return [
            {
                "date": row["date"],
                "description": row["description"] or "",
                "category": row["category"],
                "amount": row["amount"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def get_summary_stats(user_id, start=None, end=None):
    """Return the three headline stats profile.html reads.

    Exactly three keys, named for the template: `total` (number, summed --
    the `rupees` filter formats it), `count` (int) and `top_category` (str).

    An account with no expenses gets zeros and an em dash rather than an
    exception: a brand-new user landing on /profile is the normal first
    experience, not an edge case. A window that happens to contain nothing
    gets exactly the same three values, for the same reason.

    `start` and `end` are the same optional inclusive YYYY-MM-DD bounds
    get_recent_transactions() takes. All three numbers then describe the
    window rather than the account.
    """
    clause, date_params = _date_clause(start, end)
    conn = get_db()
    try:
        # Only the two columns the stats are derived from. The transaction
        # list is its own query, so pulling dates and descriptions through
        # here as well would buy nothing.
        rows = conn.execute(
            "SELECT amount, category FROM expenses WHERE user_id = ?" + clause,
            (user_id,) + date_params,
        ).fetchall()
        # Everything below runs inside the try for the same reason as
        # get_user_by_email(): the rows are materialised while the connection
        # is still open.
        if not rows:
            # No rows means no categories, so _category_totals() comes back
            # empty and indexing it would raise on a brand-new account.
            return {"total": 0, "count": 0, "top_category": "\u2014"}
        return {
            "total": sum(row["amount"] for row in rows),
            "count": len(rows),
            # Read off the shared helper rather than summed again here, so
            # this headline can never name a different category than the
            # first bar of the breakdown chart.
            "top_category": _category_totals(rows)[0][0],
        }
    finally:
        conn.close()


def get_category_breakdown(user_id, start=None, end=None):
    """Return one bar per category for `user_id`, largest first.

    One dict per category with the three keys profile.html reads:
    `category` (str), `amount` (number, formatted by the `rupees` filter) and
    `percent` (int -- it goes straight into style="width: N%", so it must be
    a whole number). Every amount reaching this table today is positive, so
    every percent is too; refunds would need a negative amount, which no
    route can create until Step 7 adds one, and Step 7 has to decide what a
    negative bar even means before this can promise anything about them.

    Whenever the total is above zero the percents sum to exactly 100: the
    bars claim to cover the whole of the spending, so they have to. Returns
    [] for a user with no expenses.

    `start` and `end` are the same optional inclusive YYYY-MM-DD bounds
    get_recent_transactions() takes. The percentages are recomputed over
    whatever the window contains, so they still sum to exactly 100 within it
    -- they are shares of the filtered spending, not of all time.
    """
    clause, date_params = _date_clause(start, end)
    conn = get_db()
    try:
        # Only the two columns the bars are built from. The date and the
        # description belong to the transaction table, not the chart.
        rows = conn.execute(
            "SELECT amount, category FROM expenses WHERE user_id = ?" + clause,
            (user_id,) + date_params,
        ).fetchall()
        # Aggregated inside the try, as in get_user_by_email(): the rows are
        # consumed while the connection is still open.
        totals = _category_totals(rows)
    finally:
        conn.close()

    grand_total = sum(amount for _, amount in totals)
    if grand_total <= 0:
        # An account whose expenses all total zero still has categories to
        # name, but no share to divide between them, so the bars render
        # empty instead of dividing by zero.
        return [
            {"category": category, "amount": amount, "percent": 0}
            for category, amount in totals
        ]

    # Largest-remainder: floor every share, then hand the leftover points
    # out one each by biggest discarded fraction. Rounding each bar on its
    # own and docking the leader for the excess is the tempting shortcut and
    # it is wrong -- 40.5 / 40.5 / 19 rounds to 41 / 41 / 19 = 101, and
    # taking the point back off the first bar leaves 40 / 41 / 19, a chart
    # that no longer descends even though the amounts still do.
    shares = [amount * 100.0 / grand_total for _, amount in totals]
    percents = [int(share) for share in shares]
    # Floors only ever undershoot, so every leftover point finds a home.
    # sorted() is stable, so tied fractions keep their existing order and the
    # larger bar is never passed over for a smaller one.
    ranked = sorted(
        range(len(shares)),
        key=lambda i: shares[i] - percents[i],
        reverse=True,
    )
    for i in ranked[:100 - sum(percents)]:
        percents[i] += 1

    return [
        {"category": category, "amount": amount, "percent": percent}
        for (category, amount), percent in zip(totals, percents)
    ]

