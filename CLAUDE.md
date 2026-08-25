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
| `GET /profile` | Implemented — renders `profile.html`, requires a session; data is still hardcoded (Step 5 wires the DB) |
| `GET /expenses/add` | Stub — Step 7 |
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
- **`database/db.py` provides `get_db()`, `init_db()`, `seed_db()`, `get_user_by_email()`, `create_user()`** (Steps 1–2, done) — plus `CATEGORIES`, `DB_PATH` and `PASSWORD_HASH_METHOD`. Callers of `get_db()` must close the connection themselves; there is no `flask.g` caching yet. There is no `get_user_by_id()` yet — Step 4 turned out not to need one (it renders hardcoded data), so **Step 5** will add it when `/profile` is wired to the database
- **`/profile` renders hardcoded data** (Step 4) — the `_PROFILE_*` constants near the top of `app.py` mirror `_SEED_EXPENSES` in `database/db.py` on purpose, so a seeded database renders the same page. Step 5 deletes that block and replaces it with real queries; keep the two in sync until then. The `rupees` Jinja filter lives beside them — **all money is ₹, never `$`**
- **`/profile` is where a signed-in user lands** (Step 4) — a successful login redirects there, and so do the "already signed in" guards on `/login` and `/register`. `GET /` deliberately still renders the landing page while signed in, so it stays reachable
- **The nav greeting links to `/profile`** (Step 4) — it is an `<a class="nav-user">`, not a span, and the `@media (max-width: 600px)` rule in `style.css` exempts it explicitly. Adding a `.nav-user` variant means checking that selector
- **Sessions carry exactly `user_id` and `user_name`** (Step 3) — the cookie is signed, not encrypted, so never put an email, password or hash in it. `app.secret_key` is set at module level in `app.py`; moving it under `__main__` silently breaks every session under `flask run` and pytest alike
- **The DB file is `spendly.db`** in the project root — `.gitignore` covers it via `*.db`, so never commit it
- **FK enforcement is manual** — SQLite foreign keys are off by default; `get_db()` must run `PRAGMA foreign_keys = ON` on every connection
- The app runs on **port 5001**, not the Flask default 5000 — don't change this