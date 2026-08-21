"""SQLite helpers for Spendly.

get_db()  -- connection with dict-like rows and foreign key enforcement on
init_db() -- create all tables (safe to call repeatedly)
seed_db() -- insert demo data exactly once (safe to call repeatedly)
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
