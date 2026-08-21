# Spec: Registration

## Overview

Step 2 makes the existing `/register` page actually work. Today `register.html` renders a fully styled three-field form that POSTs to `/register`, but the route is GET-only, so submitting it returns **405 Method Not Allowed**. This step adds POST handling: validate the submitted name, email and password; reject duplicates and bad input with an inline error; hash the password with `werkzeug.security` using `pbkdf2:sha256`; insert the row into the existing `users` table; and redirect to the login page with a success banner. It is the first step that writes user-supplied data to the database, so it also establishes the two conventions every later step inherits — user-lookup/creation helpers living in `database/db.py`, and connections being opened and closed inside those helpers rather than in route bodies.

Scope is deliberately narrow: **registration only**. No session is created, the user is not logged in automatically, and no `secret_key` is added. Sessions and `check_password_hash` are Step 3's job.

## Depends on

- **Step 1 — Database setup** (complete). Provides `get_db()`, `init_db()`, `seed_db()`, `DB_PATH`, `CATEGORIES`, `PASSWORD_HASH_METHOD`, and the `users` table with its `UNIQUE` email constraint.

Nothing else. Step 3 (login/logout) and Step 4 (profile) are **not** prerequisites and must not be implemented here.

## Routes

- `GET /register` — renders the registration form. **Already exists**; only its `methods` list changes. Public.
- `POST /register` — validates input, creates the user, redirects to `/login?registered=1` on success or re-renders `register.html` with an `error` string on failure. Public.
- `GET /login` — **modified, not new**. Must read the `registered` query parameter and pass a success flag to the template. Still GET-only in this step; its POST handler is Step 3. Public.

No other routes are added. Do **not** implement `/logout`, `/profile`, or any `/dashboard` route — `/profile` is a Step 4 stub and CLAUDE.md forbids implementing a stub out of step.

**Post-registration destination:** `/login`. There is no dashboard and no logged-in landing page yet, so login is the only correct target.

## Database changes

**No schema changes.** The `users` table already has everything registration needs:

```sql
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);
```

Verified against `database/db.py` — no migration, no new column, no new index.

Two **new helper functions** are added to `database/db.py` (no user helpers currently exist):

```python
def get_user_by_email(email):
    """Return the users row matching email, or None. Caller passes a normalised email."""

def create_user(name, email, password):
    """Hash password with PASSWORD_HASH_METHOD, insert the user, return the new id.
    Raises sqlite3.IntegrityError if the email is already taken."""
```

Both open their own connection via `get_db()` and close it in a `finally` block. `create_user` hashes internally using the existing module constant `PASSWORD_HASH_METHOD` and `generate_password_hash`, mirroring how `seed_db()` already does it — routes never see a raw hash.

**Email case-sensitivity:** the `UNIQUE` constraint has no `COLLATE NOCASE`, so `A@b.com` and `a@b.com` would both insert as separate users. Registration must normalise with `.strip().lower()` **before** the duplicate check and before the insert. Do not alter the table to add `COLLATE NOCASE` — that is a migration, and out of scope here.

## Templates

**Create:** none.

**Modify:**

- `templates/register.html`
  - Change `action="/register"` to `action="{{ url_for('register') }}"` — CLAUDE.md forbids hardcoded URLs.
  - Repopulate `name` and `email` on validation failure: `value="{{ name or '' }}"` and `value="{{ email or '' }}"`. Never repopulate the password field.
  - The `{% if error %}<div class="auth-error">{{ error }}</div>{% endif %}` block already exists — reuse it as-is. Do not switch to `flash()`.
- `templates/login.html`
  - Change `action="/login"` to `{{ url_for('login') }}` for the same reason.
  - Add a success banner shown only when the registration flag is set:
    `{% if registered %}<div class="auth-success">Account created. Sign in to continue.</div>{% endif %}`
- `templates/base.html` — **no changes.** No flash rendering block is needed, because this step passes errors as a template variable rather than through `flash()`.

## Files to change

- `app.py`
  - Add `request`, `redirect`, `url_for` to the Flask import line.
  - Add `create_user`, `get_user_by_email` to the `database.db` import.
  - `register()` → `@app.route("/register", methods=["GET", "POST"])`, handling both branches.
  - `login()` → read `request.args.get("registered")` and pass `registered=...` into `render_template`.
  - Leave the currently-unused `get_db` import alone or drop it — routes must not call it directly either way.
- `database/db.py` — append `get_user_by_email()` and `create_user()`. Do not touch `_SCHEMA`, `init_db()`, or `seed_db()`.
- `templates/register.html` — as above.
- `templates/login.html` — as above.
- `static/css/style.css` — add one `.auth-success` rule.

## Files to create

- `tests/__init__.py` — empty.
- `tests/conftest.py` — pytest fixtures. There is currently **no test scaffolding of any kind**, so this step establishes it.
- `tests/test_registration.py` — the Step 2 test suite.

**Critical fixture constraint:** `DB_PATH` is computed at import time in `database/db.py`, and `app.py` calls `init_db()` and `seed_db()` at module import. A test that imports `app` without preparing first will create and seed the real `spendly.db` in the project root. `conftest.py` must monkeypatch `database.db.DB_PATH` to a `tmp_path` file **before** `app` is imported. `get_db()` reads the module global at call time, so patching the attribute is sufficient — no refactor of `db.py` is required.

## New dependencies

**No new dependencies.** `flask==3.1.3`, `werkzeug==3.1.6`, `pytest==8.3.5` and `pytest-flask==1.3.0` are already pinned in `requirements.txt` and installed in `venv/`. `requirements.txt` is not modified.

## Rules for implementation

- **No SQLAlchemy or ORMs** — raw `sqlite3` through `get_db()` only.
- **Parameterised queries only** — `?` placeholders, never f-strings or `%` formatting in SQL.
- **Passwords hashed with werkzeug** — `generate_password_hash(password, method=PASSWORD_HASH_METHOD)`. Use the existing `PASSWORD_HASH_METHOD` constant; do not retype `"pbkdf2:sha256"` and do not accept the werkzeug default, which is scrypt and raises `AttributeError: module 'hashlib' has no attribute 'scrypt'` on this Python build.
- **Use CSS variables — never hardcode hex values.** For `.auth-success`, reuse the existing dark-green pair `--accent` (text/border) and `--accent-light` (background). There is no `--success` variable; do not invent a raw hex. If a distinct success colour is genuinely wanted, add `--success` / `--success-light` to `:root` first and use those.
- **All templates extend `base.html`** — both edited templates already do; keep it that way.
- **No DB logic in route functions** — `register()` must not call `get_db()`, write SQL, or close a connection. It calls `get_user_by_email()` / `create_user()` and nothing more.
- **Connection lifecycle:** every helper in `database/db.py` opens its own connection and closes it in `finally`. No `flask.g`, no `teardown_appcontext` — Step 1's spec flagged this as a Step 2 decision, and this is the decision. Revisit only if a single request ever needs several queries in one transaction.
- **No `session`, no `flash()`, no `app.secret_key`** in this step. Errors ride on the `error` template variable; success rides on the `registered` query parameter. Adding a secret key is Step 3's call, made once, alongside sessions.
- **Python 3.9** — no `match`, no `X | Y` type unions.
- `abort()` for HTTP errors, never a bare `return "error string"`. Validation failures are not HTTP errors — they re-render the form with `error`.
- Do not touch the port (5001), the stub routes, or `landing.css`.

**Validation rules, server-side, in this order** (client-side `required` attributes are not a substitute):

1. All three fields present after `.strip()` → else `"All fields are required."`
2. Email contains `@` and a `.` after it → else `"Enter a valid email address."`
3. Password length ≥ 8 → else `"Password must be at least 8 characters."`
4. `get_user_by_email(email)` returns None → else `"An account with that email already exists."`
5. Wrap the insert in `try/except sqlite3.IntegrityError` anyway and map it to the same duplicate message — check-then-insert is a race, and the `UNIQUE` constraint is the real guard. The constraint fires with `UNIQUE constraint failed: users.email`.

The name is stored as `.strip()`-ed but otherwise verbatim. The email is stored `.strip().lower()`-ed.

## Definition of done

Run `python app.py` (port 5001) and verify each item:

1. `GET /register` returns 200 and renders the form — unchanged from before.
2. Submitting the form with a fresh name/email/8+ char password returns a redirect to `/login?registered=1`, and the login page shows the green "Account created" banner styled with `--accent-light`.
3. `sqlite3 spendly.db "SELECT id, name, email, substr(password_hash,1,13) FROM users ORDER BY id DESC LIMIT 1;"` shows the new row, and the hash column begins with `pbkdf2:sha256`.
4. The stored email is lowercased: registering `Foo@Example.COM` stores `foo@example.com`.
5. Re-submitting the same email (any casing) re-renders `/register` with the `.auth-error` box reading "An account with that email already exists.", and no second row is inserted.
6. Submitting a 7-character password re-renders with the length error and inserts nothing.
7. Submitting a blank name re-renders with the required-fields error and inserts nothing.
8. On any validation failure the name and email inputs are still filled in and the password input is empty.
9. Page source of `/register` and `/login` contains no hardcoded `action="/register"` or `action="/login"` — both resolve through `url_for`.
10. `GET /login` with no query string shows **no** success banner.
11. `/logout`, `/profile`, and the `/expenses/*` routes still return their original stub strings — untouched.
12. `grep -n "get_db\|SELECT\|INSERT" app.py` returns no SQL and no `get_db()` call inside a route body.
13. `pytest` passes, covering at minimum: successful registration inserts exactly one row; duplicate email (differing only in case) is rejected; short password is rejected; the password is hashed, not stored in plaintext; `GET /register` is 200 and `POST /register` is no longer 405.
14. `git status` shows `spendly.db` untracked-and-ignored — the `*.db` glob in `.gitignore` still covers it.

---

### Notes for the implementer (not scope)

- `.claude/specs/01-database-setup.md` repeatedly names the database `expense_tracker.db`. That is stale — the shipped code and CLAUDE.md both use `spendly.db`. Trust the code. Any verification command in that older spec that references `expense_tracker.db` is a no-op.
- `base.html`'s footer hardcodes `/terms` and `/privacy` instead of using `url_for()`, which violates CLAUDE.md. Pre-existing, unrelated to registration — flagging it, not fixing it here.
- `register.html` has no confirm-password field and no CSRF token. Both are deliberate omissions for now: CSRF would need Flask-WTF, and CLAUDE.md forbids new pip packages.
