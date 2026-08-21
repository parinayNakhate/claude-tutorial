import os
import sqlite3

from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from database.db import create_user, get_user_by_email, init_db, seed_db

app = Flask(__name__)

# Signing key for the session cookie. Set at module level for the same reason
# as the block below: `flask run` and tests/conftest.py both import this module
# without ever executing `if __name__ == "__main__"`, so a key set there would
# leave every session silently broken under both. Never generated at startup --
# a fresh key on each reloader restart would invalidate every open session.
app.secret_key = os.environ.get(
    "SPENDLY_SECRET_KEY", "dev-only-not-for-production"
)

# Ensure the schema and demo data exist before any request is dispatched.
# Kept at module level rather than under __main__ so it also runs under
# `flask run`, which imports this module and never executes that block.
with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    # Neither auth form has anything to offer someone already signed in.
    # Guards POST as well as GET: checking only the GET branch would still
    # let a signed-in visitor create a second account by submitting the form
    # directly, which is the hole a GET-only guard leaves open.
    if session.get("user_id"):
        return redirect(url_for("landing"))

    if request.method == "GET":
        return render_template("register.html")

    # Normalise before validating: the UNIQUE index on users.email is
    # case-sensitive, so the duplicate check and the insert must both see the
    # same lowercased form. The password is never stripped -- leading and
    # trailing spaces are legitimate password characters.
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    at = email.find("@")

    # An if/elif chain rather than separate ifs: the first failure wins and
    # later rules never run, so the order the messages appear in is fixed.
    error = None
    if not name or not email or not password.strip():
        error = "All fields are required."
    elif at == -1 or "." not in email[at + 1:]:
        error = "Enter a valid email address."
    elif len(password) < 8:
        error = "Password must be at least 8 characters."
    elif get_user_by_email(email) is not None:
        error = "An account with that email already exists."

    if error is None:
        try:
            create_user(name, email, password)
        except sqlite3.IntegrityError:
            # Two simultaneous requests can both pass the check above; the
            # UNIQUE constraint is what actually prevents the duplicate.
            error = "An account with that email already exists."
        else:
            return redirect(url_for("login", registered=1))

    return render_template("register.html", error=error, name=name, email=email)


@app.route("/login", methods=["GET", "POST"])
def login():
    # Same guard as register(), for the same reason: outside the method
    # branch so a signed-in POST cannot silently overwrite the session.
    if session.get("user_id"):
        return redirect(url_for("landing"))

    if request.method == "GET":
        # `registered` and `logged_out` are set by the redirects out of
        # register() and logout(). Both compared against "1" rather than
        # tested for truthiness: request.args.get() returns the string "0"
        # for /login?logged_out=0, which Jinja treats as truthy.
        return render_template(
            "login.html",
            registered=request.args.get("registered") == "1",
            logged_out=request.args.get("logged_out") == "1",
        )

    # Normalise exactly as registration does: the UNIQUE index on users.email
    # has no COLLATE NOCASE, so Demo@Spendly.com only matches the stored form
    # once lowercased. The password is never stripped -- leading and trailing
    # spaces are legitimate password characters.
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    # Guarded so a blank submission never reaches SQLite at all.
    user = get_user_by_email(email) if email and password else None

    # An if/elif chain as in register(): the first failure wins. Registration's
    # rules deliberately do not apply -- no length minimum (the seeded demo
    # password is six characters) and no email-shape check. Both credential
    # failures share one message: naming which half was wrong would turn this
    # form into an account-enumeration oracle. Only half closed -- an unknown
    # email short-circuits before check_password_hash and so answers ~200x
    # faster, which leaks the same fact through timing. Closing that needs a
    # dummy hash comparison here; out of scope for Step 3.
    error = None
    if not email or not password:
        error = "Please enter your email and password."
    elif user is None or not check_password_hash(
            user["password_hash"], password):
        error = "Incorrect email or password."

    if error is None:
        # Exactly two keys. user_name is a snapshot so base.html can greet the
        # visitor without a query per render; a later rename feature must
        # rewrite this key in its own handler, not add a lookup here. Never the
        # email, password or hash -- the cookie is signed, not encrypted.
        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        # Redirect, never render, so a refresh does not resubmit. The landing
        # page is a placeholder destination: /profile is still a Step 4 stub
        # returning a raw string. This moves when the dashboard arrives.
        return redirect(url_for("landing"))

    return render_template("login.html", error=error, email=email)


@app.route("/logout")
def logout():
    # session.clear() on an empty session is a no-op, so hitting /logout while
    # already signed out returns the same 302 as the first time -- no abort(),
    # no traceback. The confirmation travels as a query parameter rather than a
    # flash: base.html would need a get_flashed_messages() block and a CSS
    # decision for a single message .auth-success already renders correctly.
    session.clear()
    return redirect(url_for("login", logged_out=1))


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/profile")
def profile():
    return "Profile page — coming in Step 4"


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
