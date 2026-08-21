import sqlite3

from flask import Flask, redirect, render_template, request, url_for

from database.db import create_user, get_user_by_email, init_db, seed_db

app = Flask(__name__)

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


@app.route("/login")
def login():
    # `registered` is set by the post-registration redirect. Compared against
    # "1" rather than tested for truthiness: request.args.get() returns the
    # string "0" for /login?registered=0, which Jinja treats as truthy.
    # POST handling for this route is Step 3.
    return render_template(
        "login.html", registered=request.args.get("registered") == "1"
    )


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/logout")
def logout():
    return "Logout — coming in Step 3"


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
