# Step 1 — Database Setup

## Context

`database/db.py` is currently a five-line comment stub, so Spendly has no data layer at all. Every later step — auth (Step 2/3), profile (Step 4), expense CRUD (Steps 7–9) — reads and writes through these helpers, so this step is the foundation the rest of the project is built on.

Spec: `.claude/01-database-setup.md` (note: **not** `.claude/specs/`, which doesn't exist).

Outcome: `get_db()`, `init_db()`, and `seed_db()` implemented, wired into `app.py` startup, producing a working `expense_tracker.db` with a demo user and 8 sample expenses — created safely and repeatably on every app launch.

**Scope: exactly two files change.** `database/db.py` and `app.py`. No new files, no new packages, no route changes.

---

## Decisions made up front

| Question | Decision | Why |
|---|---|---|
| DB filename | **`expense_tracker.db`** | Spec §5A allows either name. `.gitignore:2` covers only `expense_tracker.db`; there's no `*.db` glob, so `spendly.db` would get committed. |
| Connection lifecycle | `get_db()` returns an open connection; **caller closes**. No `flask.g`, no `teardown_appcontext`. | Spec §5A says only "returns the connection", and the repo has zero `g`/teardown usage today. Request-scoped connections are Step 2+ scope. |
| Python target | **3.9-compatible** | The venv is Python 3.9.6 even though `CLAUDE.md:51` claims 3.10+. No `match`, no `X \| Y` runtime annotations. |
| Seed amounts | INR (₹120–₹2,299) | Templates render `₹` (`landing.html:41,46`). |
| Verification | Throwaway scratchpad script, deleted after | Spec §8: "Files to Create: None". No `tests/` this step. |

---

## 1. `database/db.py` — replace wholesale

Structure: docstring → imports → constants → `_SCHEMA` → `get_db` → `init_db` → seed data/dates → `seed_db`.

### Constants

```python
import calendar, os, sqlite3
from datetime import date
from werkzeug.security import generate_password_hash

# db.py lives in <project_root>/database/, so climb one level to reach the root.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "expense_tracker.db")

CATEGORIES = ("Food", "Transport", "Bills", "Health",
              "Entertainment", "Shopping", "Other")   # spec §10, fixed list

DEMO_NAME, DEMO_EMAIL, DEMO_PASSWORD = "Demo User", "demo@spendly.com", "demo123"
```

`DB_PATH` must be `__file__`-relative, **not** cwd-relative — this is the most likely bug in the step and is explicitly verified below.

### Schema

```sql
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
```

Three notes:
- `DEFAULT (datetime('now'))` **must** be parenthesised — the bare form is a SQLite syntax error.
- `AUTOINCREMENT` is redundant in SQLite but the spec's constraint column asks for it. Side effect: a `sqlite_sequence` table appears; not a bug.
- `ON DELETE CASCADE` goes **beyond** the literal spec (§4B says only "FK → users.id, not null"). Included deliberately because changing an FK clause later requires a full table rebuild in SQLite.

### `get_db()`

```python
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys = ON")   # off by default; per-connection
return conn
```

Set the pragma immediately after connect — it is a silent no-op inside an open transaction. `PRAGMA` can't take a `?` placeholder, but the value is a hardcoded literal with no user input, so §11 is satisfied.

### `init_db()`

`conn.executescript(_SCHEMA)` → `conn.commit()`, wrapped in `try/finally: conn.close()`.

### Seed rows — 8 rows, all 7 categories, Food twice

```python
_SEED_EXPENSES = (
    (450.00,  "Food",          "Groceries at the local market"),
    (120.00,  "Transport",     "Metro card top-up"),
    (1850.00, "Bills",         "Electricity bill"),
    (640.00,  "Health",        "Pharmacy - monthly medicines"),
    (350.00,  "Entertainment", "Movie tickets"),
    (2299.00, "Shopping",      "Running shoes"),
    (275.00,  "Food",          "Dinner with friends"),
    (500.00,  "Other",         "Gift for a colleague"),
)
```

8 rows across 7 categories forces exactly one duplicate; Food is the natural one. Total ₹6,484 — a believable partial month.

### Dates — computed dynamically, never hardcoded

Helper `_seed_dates(count)` spreads days across the **current** month, clamped to `min(today.day, monthrange(...))` so seeds never land in the future and February/30-day months stay valid. Format with `"{:04d}-{:02d}-{:02d}".format(...)`. On 2026-08-21 this gives `08-03, 08-05, 08-08, 08-10, 08-13, 08-16, 08-18, 08-21`. Edge case: run on the 1st, all eight collapse to day 01 — still valid, and preferable to future-dated demo data.

### `seed_db()`

```python
conn = get_db()
try:
    if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None:
        return                       # idempotency guard — inside the try
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        (DEMO_NAME, DEMO_EMAIL, generate_password_hash(DEMO_PASSWORD)))
    user_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO expenses (user_id, amount, category, date, description) "
        "VALUES (?, ?, ?, ?, ?)", rows)
    conn.commit()
finally:
    conn.close()
```

- Guard on "any user exists" (spec §5C), **not** on the demo email — an email-scoped check would re-seed 8 more expenses onto a real user after the demo row is deleted.
- The early `return` stays **inside** the `try` so `finally` still closes. Easiest leak to introduce here.
- `seed_db()` must not call `init_db()` itself; `app.py` owns the ordering.

### Connection discipline — the gotcha

`with sqlite3.connect(...) as conn:` is a **transaction** manager, not a resource manager: it commits on clean exit and rolls back on exception, but **never closes**. Use explicit `conn.commit()` inside `try` / `conn.close()` in `finally` throughout.

---

## 2. `app.py` — two hunks, top of file only

```diff
 from flask import Flask, render_template

+from database.db import get_db, init_db, seed_db
+
 app = Flask(__name__)

+# Ensure schema and demo data exist before any request is dispatched.
+# Module level (not under __main__) so it also fires under `flask run`.
+with app.app_context():
+    init_db()
+    seed_db()
+
```

Placement is load-bearing: **after** `app = Flask(__name__)` (the context needs the app), **before** the routes (spec §6), and **at module level, not inside `if __name__ == "__main__":`** — `flask run`, gunicorn, and pytest all *import* `app.py` and never run the `__main__` block, so init there would mean `python app.py` works while `flask run` dies with `no such table: users`.

Two expected non-issues: `get_db` is imported but unused in this step (spec §6 mandates it; Step 2 uses it — no `# noqa`), and with `debug=True` the reloader imports the module twice per launch, so this block runs twice. `CREATE TABLE IF NOT EXISTS` plus the seed guard make that harmless — which is exactly why idempotency is a hard requirement.

---

## 3. Verification

Nothing enters the repo. `$SCRATCH` = the session scratchpad dir.

**A. Clean slate + import.** From the project root:
```bash
rm -f expense_tracker.db && ./venv/bin/python -c "import app; print('import OK')" && ls -l expense_tracker.db
```
Proves the DB is created on startup and the app imports cleanly.

**B. Throwaway checker** at `$SCRATCH/verify_db.py`, run with `./venv/bin/python`, asserting:
1. `PRAGMA table_info` — both tables have exactly the spec's columns; `amount` is `REAL`; every column `NOT NULL` except `expenses.description`.
2. `created_at` is a populated `YYYY-MM-DD HH:MM:SS` string (proves the parenthesised default fired).
3. FK **enforced**: `PRAGMA foreign_keys` returns 1, and inserting an expense with `user_id=99999` raises `sqlite3.IntegrityError` / `FOREIGN KEY constraint failed`.
4. UNIQUE email: re-inserting `demo@spendly.com` raises `UNIQUE constraint failed: users.email`.
5. Counts: 1 user, 8 expenses, 7 distinct categories, all a subset of `CATEGORIES`, all rows owned by the demo user.
6. Hashing: `password_hash != "demo123"` and `check_password_hash(hash, "demo123")` is True while `"wrong"` is False.
7. Dates: every value matches `^\d{4}-\d{2}-\d{2}$`, is in the current `YYYY-MM`, and is `<= today`.
8. **Idempotency**: call `init_db(); seed_db()` three more times → counts still 1 and 8, demo user id unchanged.
9. Row factory: `row["email"]` works (proves `sqlite3.Row`).
10. **Path resolution**: `DB_PATH == <project_root>/expense_tracker.db`, and the checker still passes when run from a different cwd with `PYTHONPATH` set — proves the path isn't cwd-relative.

**C. Server smoke.** `./venv/bin/python app.py`, confirm it binds **5001** and `GET /` returns 200; then `./venv/bin/flask --app app run --port 5001` to prove the non-`__main__` path also initialises.

**D. Leak check.** Loop `init_db(); seed_db()` ~200×; no `database is locked`, and `rm -f expense_tracker.db` succeeds afterwards.

**E. Final:** `git status` shows exactly two modified files and no new untracked ones — `expense_tracker.db` must **not** appear.

---

## 4. Conflicts and things to flag

1. **`CLAUDE.md:51` is stale** — claims Python 3.10+; the venv is 3.9.6. Code targets 3.9. Worth fixing the doc separately.
2. **`CLAUDE.md:115` is stale** — says `database/db.py` is "currently empty"; it has a 5-line comment stub. Cosmetic.
3. **Spec path** — the spec lives at `.claude/01-database-setup.md`, not `.claude/specs/`.
4. **`ON DELETE CASCADE` and the demo credentials** are deliberate additions/acceptances beyond the literal spec; both noted above. `demo123` in source is dev-only seed data and gets a comment saying so.
5. **No connection-lifecycle story yet** — every future route must remember to close. Fine for Step 1; revisit once in Step 2 rather than sprinkling `try/finally` across ten routes.

---

## 5. Sequence

1. Rewrite `database/db.py`.
2. Apply the two `app.py` hunks.
3. `rm -f expense_tracker.db`, run verification A–E.
4. Delete the scratchpad checker.
