# CLAUDE.md

## Project overview

Spendly is a lightweight personal expense tracker built with Flask and SQLite.

---

## Architecture
```
spendly/
├── app.py              # All routes — single file, no blueprints
├── database/
│   └── db.py           # SQLite helpers: get_db(), init_db(), seed_db(), user lookups
├── templates/
│   ├── base.html       # Shared layout — all templates must extend this
│   └── *.html          # One template per page
├── static/
│   ├── css/
│   │   ├── style.css       # Global styles
│   │   ├── landing.css     # Landing-page-only styles
│   │   └── profile.css     # Profile-page-only styles
│   └── js/
│       └── main.js         # Vanilla JS only
└── requirements.txt
```

**Where things belong:**
- New routes → `app.py` only, no blueprints
- DB logic → `database/db.py` only, never inline in routes
- New pages → new `.html` file extending `base.html`
- Page-specific styles → new `.css` file, not inline `<style>` tags

---

## Code style

- Python: PEP 8, snake_case for all variables and functions
- Templates: Jinja2 with `url_for()` for every internal link — never hardcode URLs
- Route functions: one responsibility only — fetch data, render template, done
- DB queries: always use parameterized queries (`?` placeholders) — never f-strings in SQL
- Error handling: use `abort()` for HTTP errors, not bare `return "error string"`

---

## Tech constraints

- **Flask only** — no FastAPI, no Django, no other web frameworks
- **SQLite only** — no PostgreSQL, no SQLAlchemy ORM, no external DB
- **Vanilla JS only** — no React, no jQuery, no npm packages
- **No new pip packages** — work within `requirements.txt` as-is unless explicitly told otherwise
- **Python 3.9** — that is what `venv/` actually runs. f-strings are fine, but no `match` statements and no `X | Y` type unions
- **`werkzeug.security` must hash with `pbkdf2:sha256`** — the default (scrypt) raises `AttributeError: module 'hashlib' has no attribute 'scrypt'` on this Python build

---

## Subagent Policy
- Always use a builtin explore subagent for codebase exploration 
  before implementing any new feature
- Always use a subagent to verify test results 
  after any implementation
- When asked to plan, delegate codebase research 
  to a subagent before presenting the plan
- always use a builtin plan subagent in plan mode

---

## Commands
```bash
# Setup
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Run dev server (port 5001)
python app.py

# Run all tests
pytest

# Run a specific test file
pytest tests/test_foo.py

# Run a specific test by name
pytest -k "test_name"

# Run tests with output visible
pytest -s
```

---

## Implemented vs stub routes

| Route | Status |
|---|---|
| `GET /` | Implemented — renders `landing.html` |
| `GET /register` | Implemented — renders `register.html` |
| `GET, POST /login` | Implemented — renders `login.html`, verifies credentials, opens the session, redirects to `/profile` |
| `GET /logout` | Implemented — clears the session, redirects to `/login?logged_out=1` |
| `GET /profile` | Implemented — renders `profile.html` from the database, scoped to `session["user_id"]`; requires a session. Optional `?start=` / `?end=` (`YYYY-MM-DD`, both inclusive, either or both omittable) narrow all three sections to one window; no query string means all time |
| `GET, POST /expenses/add` | Implemented — renders `add_expense.html`; POST validates the four fields and inserts one row scoped to `session["user_id"]`, then redirects to `/profile`; requires a session on both methods |
| `GET /expenses/<id>/edit` | Stub — Step 8 |
| `GET /expenses/<id>/delete` | Stub — Step 9 |

**Do not implement a stub route unless the active task explicitly targets that step.**

---

## Warnings and things to avoid

- **Never use raw string returns for stub routes** once a step is implemented — always render a template
- **Never hardcode URLs** in templates — always use `url_for()`
- **Never put DB logic in route functions** — it belongs in `database/db.py`
- **Never install new packages** mid-feature without flagging it — keep `requirements.txt` in sync
- **Never use JS frameworks** — the frontend is intentionally vanilla
- **`database/db.py` provides `get_db()`, `init_db()`, `seed_db()`, `get_user_by_email()`, `create_user()`** (Steps 1–2) **`get_user_by_id()`** (Step 5) and **`insert_expense()`** (Step 7) — plus `CATEGORIES`, `DB_PATH` and `PASSWORD_HASH_METHOD`. Callers of `get_db()` must close the connection themselves; there is no `flask.g` caching yet
- **`insert_expense()` is the only write path for expenses** (Step 7) — `insert_expense(user_id, amount, category, date, description=None)` in `database/db.py`, mirroring `create_user()`: it commits explicitly and returns `lastrowid`, which Steps 8–9 will need. It binds values, it does not police them — `add_expense()` has already validated every one. It is a *write* helper, so it does not make a fourth read path: Steps 8–9 still extend the same three `/profile` queries. A `user_id` naming a deleted row raises `sqlite3.IntegrityError` because FKs are on, and `add_expense()` answers that the way `profile()` does, with `session.clear()` then a redirect
- **`login_required` replaced the inline guard** (Step 7) — the decorator in `app.py` now guards `profile()` and `add_expense()`, and Steps 8–9 should use it rather than re-inlining the check. It goes **below** `@app.route`, never above, or Flask registers the unguarded function. `functools.wraps` is load-bearing twice: without it every guarded view registers as `wrapper` and the second one raises at import, and `inspect.getsource()` would stop unwrapping to the real body that the no-SQL tests grep. Wrapping the whole view is what covers POST as well as GET
- **`add_expense()` validates with `_as_number()` and `_as_day()`** (Step 7) — both beside `_clean_date_range()` in `app.py`, both presentation-side and SQL-free. `_as_day()` re-formats through `strftime` for the reason `_clean_date_range()` documents, and the write side is where that hazard is actually created: a row stored as `"2026-8-3"` sorts after `"2026-12-31"` and falls outside every date filter that ought to contain it. `_as_number()` rejects `nan` and `inf`, which `float()` accepts and a bare `> 0` waves through — one such row would make every total and bar on `/profile` unrecoverable. Amounts must be positive, which is the decision `get_category_breakdown()` was waiting on: **no negative amounts, so refunds are out of scope**
- **The form page writes no CSS of its own** (Step 7) — `add_expense.html` is the `.auth-*` shell `register.html` already established, down to Cancel sitting in the `.auth-switch` slot. `<select class="form-input">` keeps its native chrome deliberately: `appearance: none` would need a caret drawn from an embedded SVG, and that is a hex literal. `profile.css` gained only `.profile-card-head`. The nav link is a plain `<a>`, so the `@media (max-width: 600px)` rule hides it below 600px — `/profile`'s own button is the mobile path, and adding a fourth `:not()` to that selector is a cost the whole nav pays
- **The `/profile` queries live in `database/db.py`** (Step 5) — `get_recent_transactions()`, `get_summary_stats()` and `get_category_breakdown()`, one per page section, each filtering `WHERE user_id = ?`, plus the shared private `_category_totals()`. They are deliberately independent — none takes another's output — so **Steps 7–9 extend these three, they do not add a fourth path**. All three return raw numbers: the `rupees` Jinja filter in `app.py` owns the symbol, so **never format currency in the query layer**. `get_recent_transactions()` orders by `date DESC, id DESC` — the tiebreaker is load-bearing, `date` has no time component. `get_category_breakdown()` uses largest-remainder rounding so percentages sum to 100 *and* stay descending; rounding each bar independently breaks one or the other. All three take optional inclusive `start`/`end` bounds (Step 6) — `get_recent_transactions(user_id, limit=10, start=None, end=None)`, `get_summary_stats(user_id, start=None, end=None)`, `get_category_breakdown(user_id, start=None, end=None)` — built by the shared private `_date_clause()`, which returns `("", ())` when both are `None` so the unfiltered query is emitted byte for byte. **New date arguments go after `limit`, never before it** — `tests/test_backend_connection.py` calls these positionally. The filter narrows rows only: it does not change the ordering. A `limit` of `None` lifts the cap, which is what `profile()` passes once a window is active
- **`/profile` is DB-backed** (Step 5) — the Step 4 `_PROFILE_*` constants are gone. `profile()` must stay free of SQL (a test greps its source, comments included) — and so must `_clean_date_range()`, the Step 6 helper beside `_member_since()` that validates the two query-string bounds and returns `(start, end, error)`. It re-formats each bound through `strftime` before it reaches the query layer: `strptime` accepts `"2026-8-3"`, `expenses.date` is stored zero-padded, and the two compare wrong as strings, so a raw pass-through would under-report silently. `_member_since()` in `app.py` formats `users.created_at`, which is `"YYYY-MM-DD HH:MM:SS"` and so cannot use the `day` filter. A session naming a deleted user gets `session.clear()` then a redirect — leaving it set would bounce between `/profile` and `/login` forever. **All money is ₹, never `$`**
- **`/profile` is where a signed-in user lands** (Step 4) — a successful login redirects there, and so do the "already signed in" guards on `/login` and `/register`. `GET /` deliberately still renders the landing page while signed in, so it stays reachable
- **The nav greeting links to `/profile`** (Step 4) — it is an `<a class="nav-user">`, not a span, and the `@media (max-width: 600px)` rule in `style.css` exempts it explicitly. Adding a `.nav-user` variant means checking that selector
- **Sessions carry exactly `user_id` and `user_name`** (Step 3) — the cookie is signed, not encrypted, so never put an email, password or hash in it. `app.secret_key` is set at module level in `app.py`; moving it under `__main__` silently breaks every session under `flask run` and pytest alike
- **The DB file is `spendly.db`** in the project root — `.gitignore` covers it via `*.db`, so never commit it
- **FK enforcement is manual** — SQLite foreign keys are off by default; `get_db()` must run `PRAGMA foreign_keys = ON` on every connection
- The app runs on **port 5001**, not the Flask default 5000 — don't change this