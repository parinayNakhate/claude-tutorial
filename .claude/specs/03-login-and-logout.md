# Spec: Login and Logout

## Overview

Step 2 shipped registration: a visitor can create an account, the row lands in `users` with a `pbkdf2:sha256` hash, and they are bounced to `/login?registered=1`. From there the trail goes cold. `templates/login.html` already renders a `<form method="POST" action="{{ url_for('login') }}">`, but `app.py` declares `@app.route("/login")` with no `methods=`, so **submitting the sign-in form today returns 405 Method Not Allowed** — precisely the state `/register` was in before Step 2. `/logout` is still a stub returning the raw string `"Logout — coming in Step 3"`, the app has **no `app.secret_key` and has never touched `session`**, and `base.html` renders "Sign in" and "Get started" unconditionally on every page whether or not anyone is signed in. This step closes that loop: it verifies a submitted password against the stored hash, establishes the application's first session, teaches the shared layout to tell a signed-in visitor from an anonymous one, and turns `/logout` into a real route.

Scope is deliberately narrow: **authentication only**. This step adds the session mechanism and the two routes that open and close it, plus a guard keeping signed-in visitors out of both auth forms. It does **not** add a `login_required` decorator, does not protect any *content* route, does not implement `/profile` or any other stub, and does not build a dashboard. Step 2's spec deferred exactly one decision to this step — *"Adding a secret key is Step 3's call, made once, alongside sessions."* — and this is that call.

> **Amended during implementation.** This spec originally scoped the signed-in guard to `GET /login` only, on the grounds that `/register` was Step 2's territory. That was wrong: hiding the sign-in form from a signed-in user while leaving the sign-up form fully open is an indefensible asymmetry, and a GET-only guard leaves the form itself submittable. `register()` is therefore in scope for this step, and both guards cover POST as well as GET. See rule 9.

---

## Depends on

- **Step 1 — Database setup.** Provides `get_db()`, `init_db()`, `seed_db()`, `DB_PATH`, `CATEGORIES`, `PASSWORD_HASH_METHOD`, and the `users` table.
- **Step 2 — Registration.** Provides `create_user()` and `get_user_by_email()` in `database/db.py`, the populated `users.password_hash` column, `templates/login.html` with its POST form and `{% if error %}` / `{% if registered %}` banner blocks, the `.auth-error` / `.auth-success` CSS, and the `tests/` harness (`conftest.py` with its temp-DB redirect and autouse `clean_tables` fixture).

Both are complete on `main`. Nothing in this step is blocked.

---

## Routes

- `GET, POST /login` — **modified, not new.** Currently GET-only. Add `methods=["GET", "POST"]`. GET renders `login.html` and must keep its existing `registered=request.args.get("registered") == "1"` behaviour. POST validates the credentials, writes the session, and redirects. Access: **public**.
- `GET /logout` — **modified, not new.** Currently a stub returning a raw string. Clears the session and redirects to `/login?logged_out=1`. Access: **public** — it must be safe to hit while already signed out, and must not `abort()` in that case.
- `GET, POST /register` — **modified, guard only.** Its validation, hashing and redirect behaviour are Step 2's and must not change. It gains one thing: the same signed-in guard `/login` gets, ahead of the method branch. Access: **anonymous only**.

**No new routes.** No route path is added or removed; three existing routes change behaviour.

Explicitly out of scope: do **not** implement `/profile`, `/expenses/add`, `/expenses/<id>/edit`, or `/expenses/<id>/delete`. They stay exactly as they are, raw strings included. CLAUDE.md: *"Do not implement a stub route unless the active task explicitly targets that step."*

---

## Database changes

**No database changes.** Verified against `database/db.py`: the `users` table already carries `id`, `name`, `email` (`NOT NULL UNIQUE`), `password_hash` (`NOT NULL`), and `created_at`, and `get_user_by_email()` already selects `password_hash` in its column list:

```sql
SELECT id, name, email, password_hash, created_at FROM users WHERE email = ?
```

That row is everything a login handler needs. No new table, no new column, no new constraint, no migration.

**No new functions in `database/db.py` either.** In particular, do **not** add `get_user_by_id()` in this step — nothing here needs it, because the session carries the display name directly. It becomes necessary when `/profile` needs to render live user data; that is Step 4's call.

The one import `database/db.py` does **not** currently have is `check_password_hash`. See *Rules for implementation* for where verification belongs.

---

## Templates

**Create:** none.

**Modify:**

- **`templates/base.html`** — the substantial change, and the first time this file is touched since Step 1. The `<div class="nav-links">` block currently hardcodes both anonymous links. Wrap it in a conditional on `session.user_id`:
  - **Signed out** (unchanged from today): `Sign in` → `url_for('login')`, and `Get started` → `url_for('register')` with class `nav-cta`.
  - **Signed in**: a greeting showing `session.user_name` in a `<span class="nav-user">`, and a `Sign out` link → `url_for('logout')`.
  - Flask exposes `session` to Jinja automatically — **no `@app.context_processor` and no `g` are needed**, and none should be added.
  - Do **not** add a `get_flashed_messages()` block. See the flash decision below.
- **`templates/login.html`** — two small additions, both mirroring patterns already in the file:
  - A third banner, `{% if logged_out %}<div class="auth-success">You have been signed out.</div>{% endif %}`, rendered inside `.auth-card` alongside the existing `registered` banner. Reuse `.auth-success` verbatim; **no new CSS class**.
  - Make the email field sticky on a failed attempt — `value="{{ email or '' }}"` — for parity with `register.html`. The password field is never repopulated.
  - The existing `{% if error %}<div class="auth-error">{{ error }}</div>{% endif %}` block is already correct and needs **no change**; the login handler passes the same `error` variable registration does.

Both files already extend or are `base.html`; no template gains an inline `<style>` tag.

---

## Files to change

| File | Change |
|---|---|
| `app.py` | Import `session` from `flask` and `check_password_hash` from `werkzeug.security`. Set `app.secret_key` at module level. Rewrite `login()` to handle GET and POST. Rewrite `logout()` to clear the session and redirect. Move `logout()` up out of the "Placeholder routes" banner section into the real `# Routes` section. Add the signed-in guard to `login()` and `register()` (rule 9) — the only change `register()` receives. |
| `templates/base.html` | Conditional nav on `session.user_id`. |
| `templates/login.html` | `logged_out` banner; sticky `email` value. |
| `static/css/style.css` | One new rule, `.nav-user`, for the signed-in greeting. Variables only — no hex literals. |
| `tests/test_registration.py` | `test_stub_routes_are_untouched` currently asserts `GET /logout` returns `"Logout — coming in Step 3"`. Remove `/logout` from that test's mapping — the other four stubs stay asserted. |
| `CLAUDE.md` | Route table: `GET /login` → `GET, POST /login` "Implemented"; `GET /logout` → "Implemented — clears session, redirects to `/login`". Also correct the stale warning at the bottom that lists `database/db.py` as providing only `get_db()/init_db()/seed_db()` — it also provides `get_user_by_email()` and `create_user()`. |

## Files to create

| File | Purpose |
|---|---|
| `tests/test_login.py` | Full coverage for this step. Follows the existing conventions: takes the `client` fixture supplied by `pytest-flask`, relies on the autouse `clean_tables` fixture, and creates its own user (the demo user is deleted before every test). Uses `client.session_transaction()` to assert on session contents. |

## New dependencies

**No new dependencies.** `session` and `flash` ship with Flask 3.1.3; `check_password_hash` ships with Werkzeug 3.1.6. Both are already pinned in `requirements.txt`. `os` — needed for reading the secret key from the environment — is in the standard library. `requirements.txt` is not modified.

---

## Rules for implementation

**Mandatory project rules:**

- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`

**Step-specific rules:**

1. **The secret key is set once, at module level.** Place it immediately after `app = Flask(__name__)`, alongside the existing `with app.app_context(): init_db(); seed_db()` block, and for the same documented reason: `flask run` and `tests/conftest.py` both import `app.py` without ever executing `if __name__ == "__main__"`. A key set inside that block would leave every session broken under both. Read it from the environment with a development fallback:

   ```python
   app.secret_key = os.environ.get("SPENDLY_SECRET_KEY", "dev-only-not-for-production")
   ```

   Add `import os` to the stdlib import group. Do not generate the key randomly at startup — that would invalidate every session on each reload.

2. **Password verification uses `check_password_hash`, never a string comparison** and never a re-hash-and-compare. The stored hash is `pbkdf2:sha256`; `check_password_hash` reads the method out of the hash string itself, so nothing in this step passes `method=` anywhere.

3. **Where verification lives.** Import `check_password_hash` into `app.py` and call it in the route against `user["password_hash"]`. This does not violate *"never put DB logic in route functions"* — `get_user_by_email()` remains the only thing that touches SQLite, and hash checking is not DB logic. Do **not** add a `verify_user()` helper to `database/db.py` in this step; keeping the credential check visible in the route is the teaching point.

4. **Normalise the email exactly as registration does:** `request.form.get("email", "").strip().lower()`. The `UNIQUE` index on `users.email` has **no `COLLATE NOCASE`**, so `Demo@Spendly.com` will not match the stored `demo@spendly.com` unless it is lowercased first. The password is read with `request.form.get("password", "")` and is **never** `.strip()`ed — leading and trailing spaces are legitimate password characters, and stripping would reject a correct password.

5. **Never apply registration's validation rules to login.** No 8-character minimum, no `@`/dot email-shape check. `DEMO_PASSWORD` in `database/db.py` is `"demo123"` — six characters — so a length rule on the login form would permanently lock out the seeded `demo@spendly.com` account. Login validates that the fields are non-empty and that the credentials match. Nothing else.

6. **One generic error message for both failure modes.** An unknown email and a wrong password must both produce the **exact same** string: `"Incorrect email or password."` Do not tell the visitor which half was wrong — that turns the login form into an account-enumeration oracle. Use the same `if/elif` chain style as `register()`, first failure wins:

   1. `not email or not password` → `"Please enter your email and password."`
   2. user is `None` **or** `check_password_hash(...)` is `False` → `"Incorrect email or password."`

   On failure: `return render_template("login.html", error=error, email=email)` — a 200 with the form redisplayed, not a redirect and not an `abort()`.

7. **Session contents are exactly two keys**, written only after a successful check:

   ```python
   session["user_id"] = user["id"]
   session["user_name"] = user["name"]
   ```

   `user_id` is the identity; `user_name` exists so `base.html` can greet the visitor without a database query on every page render. Nothing else goes in the session — no email, and **never** the password or the hash.

8. **Post-login destination is `GET /` (`url_for("landing")`).** This needs stating because the obvious target does not exist yet: `/profile` is a Step 4 stub returning a raw string, and CLAUDE.md forbids implementing a stub out of step, so redirecting there would land the user on unstyled placeholder text. The landing page renders through `base.html` and therefore immediately shows the signed-in nav, which makes the login visibly successful. When the dashboard arrives in a later step, this redirect moves — it is a placeholder destination, not a permanent one. Redirect, never `render_template`, so a refresh does not resubmit the form (Post/Redirect/Get, same as `register()`).

9. **Neither auth form is reachable while signed in.** `/login` and `/register` both check `session.get("user_id")` and redirect to `url_for("landing")` rather than rendering. Two requirements on the placement:

   - The check goes **at the top of the function, ahead of the `if request.method == "GET"` branch** — not inside it. A GET-only guard hides the page while leaving the form fully submittable: a signed-in visitor could still `POST /register` to create a second account, or `POST /login` to silently re-authenticate as somebody else. The hole is the whole point of the rule, so guarding only GET fails it.
   - Apply it to **both** routes. Guarding the sign-in form while leaving the sign-up form open is an asymmetry with no defence.

   Beyond this guard, `register()` is untouched — its validation, hashing, error strings and redirect are Step 2's and stay exactly as they are.

10. **`/logout` uses `session.clear()`**, accepts GET, and redirects to `url_for("login", logged_out=1)`. It must not `abort()` or error when no one is signed in — `session.clear()` on an empty session is a no-op, and hitting `/logout` twice must give the same result both times. It must **not** return a raw string: CLAUDE.md, *"Never use raw string returns for stub routes once a step is implemented."*

11. **No `flash()` in this step, and no `get_flashed_messages()` block in `base.html`.** The sign-out confirmation travels as a query parameter — `/login?logged_out=1` — read with `request.args.get("logged_out") == "1"`, the identical pattern Step 2 established for `registered`. Compare against the string `"1"`, never truthiness: `request.args.get()` returns the string `"0"` for `?logged_out=0`, which Jinja treats as truthy. Introducing flash infrastructure would mean a new `base.html` block and a CSS decision for a single message that the existing `.auth-success` class already renders correctly.

12. **Do not add a `login_required` decorator or any `@app.before_request` hook.** No route in this step needs protecting — `/profile` and the expense routes are still stubs. Gating them is Step 4's work, and building the decorator now would leave dead code.

13. **`static/css/style.css` gains exactly one rule**, `.nav-user`, using existing variables (`--ink-muted`, `--font-body`) for the greeting text. The `Sign out` link reuses the existing `.nav-links a` styling — do not give it `.nav-cta`, which is the high-emphasis conversion style. Do **not** touch the existing `.auth-error` rule while you are in the file; its hardcoded `#f5c6c2` border is a known pre-existing violation and fixing it is out of scope for this step.

14. **Every internal link uses `url_for()`.** The nav's new `Sign out` link is `{{ url_for('logout') }}`. Do not fix the footer's hardcoded `/terms` and `/privacy` — pre-existing, already flagged in Step 2's spec, still out of scope.

15. **Route functions stay single-responsibility** and every `database/db.py` helper keeps closing its own connection in `finally`. No `flask.g`, no `teardown_appcontext` — Step 2 made that decision and this step does not revisit it.

---

## Definition of done

Run `python app.py` (port 5001) and verify each item:

1. `GET /login` returns 200 and renders the sign-in form, unchanged in appearance from before this step.
2. Submitting the sign-in form no longer 405s. `curl -i -X POST localhost:5001/login -d "email=demo@spendly.com&password=demo123"` returns **302** with `Location: /`.
3. Signing in as `demo@spendly.com` / `demo123` in a browser lands on the landing page, and the nav now shows **"Demo User"** and a **"Sign out"** link instead of "Sign in" and "Get started". The six-character demo password is accepted — no length error appears.
4. That nav state persists across pages: navigate to `/terms` and `/privacy` and the signed-in nav is still rendered on both.
5. Signing in with a **correct email and wrong password** returns 200, redisplays the form, and shows exactly `Incorrect email or password.` in a `div.auth-error`. The email field is still filled in; the password field is empty.
6. Signing in with an **email that has no account** returns 200 and shows the **identical** string `Incorrect email or password.` — byte-for-byte the same as item 5. `grep -c "Incorrect email or password" app.py` returns `1`, confirming one shared message rather than two.
7. Submitting with a blank email or blank password shows `Please enter your email and password.` and does not create a session.
8. Email is case-insensitive on login: `Demo@Spendly.COM` with the correct password signs in successfully.
9. A password with meaningful whitespace is not mangled: register an account whose password ends in a space, then sign in with that exact password — it succeeds.
10. Neither auth form is reachable while signed in, and the guard covers POST as well as GET:
    - `GET /login` and `GET /register` each return 302 to `/` instead of rendering.
    - `POST /register` with a valid new payload returns 302 to `/` and creates **no** row — check with `sqlite3 spendly.db "SELECT COUNT(*) FROM users;"` either side of the request.
    - `POST /login` carrying a *different* account's valid credentials returns 302 to `/` and leaves the session's `user_id` unchanged.
    - Signed out, both forms still render: `GET /login` and `GET /register` each return 200. The guard must not lock anonymous visitors out of the thing they came for.
11. `GET /logout` returns 302 to `/login?logged_out=1`; the resulting page shows `You have been signed out.` in a `div.auth-success`, and the nav is back to "Sign in" / "Get started".
12. `GET /logout` while already signed out also returns 302 to `/login?logged_out=1` with no error and no traceback.
13. `GET /login?logged_out=0` shows **no** sign-out banner, and `GET /login` with no query string shows neither banner.
14. After signing out, the browser back button onto a cached page then a reload shows the signed-out nav — the session cookie is genuinely gone.
15. No secrets in the session cookie: sign in, then inspect the `session` cookie in devtools and confirm it decodes to `user_id` and `user_name` only — no email, no password, no hash.
16. `python -c "import app"` succeeds and `app.secret_key` is set at import time: `python -c "import app; print(bool(app.app.secret_key))"` prints `True` — proving the key is not hidden inside the `__main__` block.
17. The other stubs are untouched: `/profile`, `/expenses/add`, `/expenses/1/edit`, and `/expenses/1/delete` each still return 200 with their original placeholder strings.
18. No raw string returns and no SQL leaked into the routes: `grep -n "return \"" app.py` shows only the four remaining stub routes, and `grep -n "SELECT\|INSERT\|UPDATE\|get_db" app.py` returns nothing.
19. `pytest` passes with the whole suite green, including the updated `tests/test_registration.py` and a new `tests/test_login.py` covering at minimum: successful login sets `session["user_id"]` and `session["user_name"]`; wrong password rejected with no session written; unknown email produces the same message; blank fields rejected; uppercase email accepted; `GET /login` and `GET /register` both redirect when signed in; `POST /register` while signed in creates no account; `POST /login` while signed in does not overwrite the session; logout clears the session; logout while signed out is harmless; and the `logged_out` banner respects the `== "1"` comparison.
20. `git status` shows only the intended files modified plus `tests/test_login.py` as new — `spendly.db` never appears, and `requirements.txt` is unchanged.

---

### Notes for the implementer (not scope)

- **`session["user_name"]` is a snapshot.** If a later step lets a user rename themselves, the nav greeting will show the stale name until they sign out and back in. The fix at that point is to re-write the session key inside the rename handler, not to add a per-request database lookup. Worth a comment in the code.
- **`get_user_by_id()` does not exist** in `database/db.py`. Step 4's `/profile` will need it — the current session carries no email or `created_at`. Flagged here so it is not a surprise.
- **The Flask session cookie is signed, not encrypted.** Its contents are readable by anyone holding the cookie; only tampering is prevented. That is exactly why rule 7 caps the payload at an id and a display name. Deploying this for real means setting `SPENDLY_SECRET_KEY` in the environment and serving over HTTPS with `SESSION_COOKIE_SECURE`; both are out of scope for a local teaching app.
- **No CSRF token on the login form**, matching registration. Adding one properly needs Flask-WTF, and CLAUDE.md forbids new pip packages. Deliberate, and consistent with Step 2.
- **No rate limiting or lockout** on failed sign-in attempts. A real deployment needs it; it would require either new state in the database or a new package, so it is not this step's problem.
- **`tests/conftest.py` sets `TESTING=True` but no `SECRET_KEY`.** That is fine once rule 1 is followed — the module-level key is in place by the time `conftest.py` imports `app`. If sessions come back empty in tests, the key ended up in the wrong place.
- **CLAUDE.md's route table drifts every step.** It is listed under *Files to change* here; keep it honest.
