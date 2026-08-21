"""Shared pytest fixtures for the Spendly suite.

Import order is the whole point of this file. database/db.py resolves DB_PATH
at import time, and app.py runs init_db() + seed_db() at import time too. So
the throwaway database is wired up here, at module scope, *before* `app` is
imported -- conftest.py is imported before any test module is collected, which
is the only hook early enough to be reliable. Doing it in a fixture would be
too late for any test module that imports `app` at its own module level, and
the real spendly.db would be created and seeded.
"""

import atexit
import os
import shutil
import sys
import tempfile

import pytest

# Project root on sys.path regardless of the cwd pytest was launched from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database.db as db  # noqa: E402

# Redirect the module global before anything can read it. get_db() looks
# DB_PATH up on every call, so rebinding the attribute is enough -- db.py needs
# no refactor to be testable.
_TMP_DIR = tempfile.mkdtemp(prefix="spendly-tests-")
db.DB_PATH = os.path.join(_TMP_DIR, "test_spendly.db")

# The directory is created at import time, so it has to be torn down by
# something that also fires when pytest never reaches a session -- a collection
# error, or an abort. atexit covers those; a session-scoped fixture would not.
atexit.register(shutil.rmtree, _TMP_DIR, True)

# Safe now: this import creates and seeds the temp file, never spendly.db.
import app as app_module  # noqa: E402


@pytest.fixture
def app():
    """The Flask application in testing mode.

    pytest-flask derives its `client` fixture from a fixture named exactly
    `app`, so the name is not a matter of taste.
    """
    app_module.app.config.update(TESTING=True)
    return app_module.app


@pytest.fixture(autouse=True)
def clean_tables():
    """Give every test an empty users table.

    Truncation rather than re-running the schema helpers: init_db() is
    idempotent but never deletes rows, so it buys no isolation, and seed_db()
    would put the demo user back -- which would turn every "exactly one row"
    assertion into two. init_db() has already run once, at app import.
    """
    conn = db.get_db()
    try:
        # Deleted explicitly rather than leaning on ON DELETE CASCADE so the
        # order of these statements does not matter.
        conn.execute("DELETE FROM expenses")
        conn.execute("DELETE FROM users")
        # Restart AUTOINCREMENT ids at 1 so tests never depend on run order.
        conn.execute(
            "DELETE FROM sqlite_sequence WHERE name IN ('users', 'expenses')"
        )
        conn.commit()
    finally:
        conn.close()
    yield
