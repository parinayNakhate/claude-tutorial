import os
import sqlite3
from datetime import datetime

from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from database.db import (
    create_user,
    get_category_breakdown,
    get_recent_transactions,
    get_summary_stats,
    get_user_by_email,
    get_user_by_id,
    init_db,
    seed_db,
)

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
# Profile page helpers                                                #
# ------------------------------------------------------------------ #

# Step 4's _PROFILE_* constants used to live here. They are gone: /profile
# reads real data now, through the per-section query helpers in
# database/db.py. Only the presentation bits stay on this side.


def _member_since(created_at):
    """Format a stored users.created_at as "January 2026".

    users.created_at is written by SQLite's datetime('now') default, so it
    arrives as "YYYY-MM-DD HH:MM:SS" -- with a time component, which is why
    this cannot reuse the `day` filter: that one parses "%Y-%m-%d" only, so
    it would hit its raw-string fallback and print seconds into the page
    header. The bare date form is accepted too, so a fixture or a hand-written
    row that stored only "2026-01-15" still formats.

    Anything unparseable comes back untouched, mirroring `day`: a malformed
    timestamp should spoil one line of the header, not raise mid-render and
    take the whole page down.
    """
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(created_at, fmt).strftime("%B %Y")
        except (TypeError, ValueError):
            continue
    return created_at


def _clean_date_range(start, end):
    """Validate the two optional /profile date bounds.

    Takes the raw query-string values and returns (start, end, error): each
    bound is either a canonical "YYYY-MM-DD" string safe to hand to the query
    layer, or None meaning no bound on that side; `error` is a message for the
    template, or None when there is nothing to say.

    Presentation-side only, like _member_since() -- it parses text and never
    reaches for the database.

    Each side is parsed on its own, so ?start= alone is a perfectly good
    open-ended-forward range, and one unusable value does not throw away a
    usable one beside it. A bound that will not parse is dropped rather than
    guessed at, and says so: silently ignoring it would show all-time numbers
    under a filter the visitor believes is applied.

    Re-formatted through strftime rather than passed through as typed: strptime
    happily accepts "2026-8-3", expenses.date is stored zero-padded, and the
    two compare wrong as strings -- "2026-8-3" sorts after "2026-12-31" -- so
    the raw form would quietly under-report with no error to show for it.

    A range whose start falls after its end is thrown away whole. It is
    answerable -- it just always answers "nothing" -- but an empty page under a
    range nobody could have meant reads as a broken one.
    """
    cleaned = []
    error = None
    for value in (start, end):
        if not value:
            # Missing, or a form submitted with the box left blank. Both mean
            # "no bound here", and neither is a mistake worth reporting.
            cleaned.append(None)
            continue
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
        except (TypeError, ValueError):
            cleaned.append(None)
            error = "Enter dates as YYYY-MM-DD."
            continue
        cleaned.append(parsed.strftime("%Y-%m-%d"))

    clean_start, clean_end = cleaned
    if clean_start and clean_end and clean_start > clean_end:
        # Both parsed, so both are zero-padded and a plain string comparison
        # orders them correctly.
        return None, None, "The start date cannot be after the end date."

    return clean_start, clean_end, error


@app.template_filter("rupees")
def rupees(value):
    """Format a number as INR with thousands separators: 6484.0 -> ₹6,484.00.

    Spendly is rupees throughout -- there is no currency setting and no other
    symbol should ever reach a template. Western grouping rather than the
    lakh/crore form: the two agree below six digits, and stdlib has no Indian
    grouping without a locale that is not guaranteed to be installed.
    """
    return "₹{:,.2f}".format(value)


@app.template_filter("day")
def day(value):
    """Format a stored YYYY-MM-DD date for display: 2026-08-25 -> 25 Aug 2026.

    SQLite keeps expenses.date as TEXT in exactly this shape, so Step 5 can
    pass its rows straight through. Anything unparseable falls back to the raw
    string -- a malformed date should look wrong in one table cell, not raise
    mid-render and take the whole page down.
    """
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return value
    # Day built by hand rather than with %-d: that flag is glibc/BSD only and
    # blows up on Windows, which CLAUDE.md's setup notes still support.
    return "{} {}".format(parsed.day, parsed.strftime("%b %Y"))


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
        return redirect(url_for("profile"))

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
        return redirect(url_for("profile"))

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
        # Redirect, never render, so a refresh does not resubmit (Post/Redirect/
        # Get, same as register()). Signing in lands on /profile: the landing
        # page was only ever a placeholder target, chosen in Step 3 because
        # /profile was still a stub returning a raw string. It renders now, so
        # this is the destination Step 3's spec said would replace it.
        return redirect(url_for("profile"))

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


@app.route("/profile")
def profile():
    # The inverse of the guard in login() and register(): those two turn a
    # signed-in visitor away, this one turns an anonymous visitor away. A
    # redirect rather than abort(401) because someone who is simply not signed
    # in has an obvious next action, and it is the sign-in form. No ?next=
    # parameter -- an unvalidated one is an open redirect, and nothing here
    # needs it yet.
    # TODO: extract to a login_required decorator once Steps 7-9 add the
    # expense routes; with one call site it would be dead abstraction today.
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user_id = session["user_id"]
    user = get_user_by_id(user_id)

    # The cookie is signed, so the id is genuine -- but the row it names can
    # be gone, an account removed while its owner was still signed in. Clear
    # the session before redirecting: login() sends anyone still carrying a
    # user_id straight back here, so a stale session left in place would
    # bounce between the two pages forever.
    if user is None:
        session.clear()
        return redirect(url_for("login"))

    # Both bounds are optional and default to empty rather than None, so the
    # template can echo them back into the form without a filter. The raw
    # values go to the form; only the validated pair reaches the query layer.
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    clean_start, clean_end, filter_error = _clean_date_range(start, end)

    # A window the visitor drew themselves is already bounded, so the ten-row
    # cap comes off inside it -- otherwise the table would show ten rows
    # underneath a headline counting the whole window. Unfiltered, the cap
    # stays: an account's whole history has no bound at all.
    row_cap = None if (clean_start or clean_end) else 10

    # One call per section of the page, and all three are given the same
    # validated window -- that is what stops the stats, the bars and the table
    # from ever describing different spans of time. With no query string both
    # bounds are None and these are the three calls Step 5 made. The name is
    # read from the session by the template itself, exactly as base.html
    # already does -- passing it here would just shadow the same value.
    return render_template(
        "profile.html",
        email=user["email"],
        member_since=_member_since(user["created_at"]),
        expenses=get_recent_transactions(
            user_id, limit=row_cap, start=clean_start, end=clean_end
        ),
        summary=get_summary_stats(user_id, start=clean_start, end=clean_end),
        breakdown=get_category_breakdown(
            user_id, start=clean_start, end=clean_end
        ),
        start=start,
        end=end,
        applied_start=clean_start,
        applied_end=clean_end,
        filter_error=filter_error,
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
