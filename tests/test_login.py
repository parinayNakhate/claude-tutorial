"""Tests for Step 3 -- login and logout."""

import inspect
import os

import app as app_module
import database.db as db

USER = {
    "name": "Grace Hopper",
    "email": "grace@example.com",
    "password": "hopper1906",
}

WRONG_CREDENTIALS = b"Incorrect email or password."
MISSING_FIELDS = b"Please enter your email and password."


def _create_user(**overrides):
    """Insert the test user straight through db.create_user().

    Not POST /register: registration enforces an 8-character minimum, so the
    six-character password this step must accept (DEMO_PASSWORD) cannot be
    created through the form at all. Going via the helper also keeps a login
    failure from being blamed on a registration regression.
    """
    fields = dict(USER, **overrides)
    return db.create_user(fields["name"], fields["email"], fields["password"])


def _login(client, **overrides):
    """POST the valid credentials with `overrides` applied."""
    fields = dict(USER, **overrides)
    return client.post(
        "/login",
        data={"email": fields["email"], "password": fields["password"]},
    )


def _session(client):
    """The client's session as a plain dict.

    pytest-flask pushes a request context for the whole test, so the ambient
    flask.session belongs to that throwaway context, not to this client.
    session_transaction() opens the client's own cookie in a fresh context,
    which is the only reading that means anything here.
    """
    with client.session_transaction() as session:
        return dict(session)


def _sign_in(client, user_id=1, user_name=USER["name"]):
    """Put a signed-in session in the client's cookie jar without a POST.

    On exit session_transaction() re-signs the session and writes it back to
    the jar, so the next request arrives already authenticated. Used where the
    point of the test is what happens *while* signed in, not how it got there.
    """
    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["user_name"] = user_name


def _error(response):
    """The text inside the response's div.auth-error, or None."""
    body = response.data.decode()
    opening = '<div class="auth-error">'
    start = body.find(opening)
    if start == -1:
        return None
    start += len(opening)
    return body[start:body.find("</div>", start)]


def _source(app, template):
    """The raw template source, before Jinja renders it."""
    return app.jinja_env.loader.get_source(app.jinja_env, template)[0]


# ------------------------------------------------------------------ #
# The route accepts POST at all                                       #
# ------------------------------------------------------------------ #

def test_post_login_is_no_longer_405(client):
    # login.html has shipped a POST form since Step 2 against a GET-only
    # route. This is the symptom that started the step.
    _create_user()
    response = _login(client)
    assert response.status_code == 302


def test_get_login_still_renders_the_form(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b"Welcome back" in response.data


# ------------------------------------------------------------------ #
# The happy path                                                      #
# ------------------------------------------------------------------ #

def test_successful_login_redirects_to_landing(client):
    _create_user()
    response = _login(client)
    assert response.status_code == 302
    # Werkzeug 3 emits a relative Location.
    assert response.headers["Location"] == "/"


def test_successful_login_writes_exactly_two_session_keys(client):
    user_id = _create_user()
    _login(client)
    # Equality, not membership: this is the assertion that proves no email,
    # password or hash leaked into the signed cookie.
    assert _session(client) == {
        "user_id": user_id,
        "user_name": USER["name"],
    }


def test_uppercase_email_signs_in(client):
    user_id = _create_user()
    response = _login(client, email="GRACE@Example.COM")
    assert response.status_code == 302
    assert _session(client)["user_id"] == user_id


def test_surrounding_whitespace_in_email_is_ignored(client):
    _create_user()
    response = _login(client, email="  grace@example.com  ")
    assert response.status_code == 302


def test_short_password_is_accepted(client):
    # Bound to the real constants so it keeps its meaning if the demo
    # credentials move. demo123 is six characters -- registration would
    # reject it, and a length rule here would lock the seeded account out.
    _create_user(email=db.DEMO_EMAIL, password=db.DEMO_PASSWORD)
    response = _login(
        client, email=db.DEMO_EMAIL, password=db.DEMO_PASSWORD
    )
    assert response.status_code == 302
    assert _session(client)["user_name"] == USER["name"]


def test_password_with_trailing_space_signs_in(client):
    _create_user(password="correct horse ")
    response = _login(client, password="correct horse ")
    assert response.status_code == 302


def test_password_stripped_of_its_trailing_space_is_rejected(client):
    # The pair with the test above proves .strip() is absent from the
    # password path in both directions.
    _create_user(password="correct horse ")
    response = _login(client, password="correct horse")
    assert response.status_code == 200
    assert WRONG_CREDENTIALS in response.data


def test_registered_user_can_sign_in_end_to_end(client):
    # The only test that crosses both steps: proves create_user()'s hash and
    # check_password_hash() interoperate through the real form path.
    client.post(
        "/register",
        data={
            "name": USER["name"],
            "email": USER["email"],
            "password": USER["password"],
        },
    )
    response = _login(client)
    assert response.status_code == 302
    assert _session(client)["user_name"] == USER["name"]


# ------------------------------------------------------------------ #
# One message for both failure modes                                  #
# ------------------------------------------------------------------ #

def test_wrong_password_is_rejected(client):
    _create_user()
    response = _login(client, password="not-the-password")
    assert response.status_code == 200
    assert WRONG_CREDENTIALS in response.data
    assert _session(client) == {}


def test_unknown_email_is_rejected(client):
    response = _login(client, email="nobody@example.com")
    assert response.status_code == 200
    assert WRONG_CREDENTIALS in response.data
    assert _session(client) == {}


def test_both_failure_modes_render_an_identical_banner(client):
    _create_user()
    wrong_password = _login(client, password="not-the-password")
    unknown_email = _login(client, email="nobody@example.com")
    # The banner text, not the whole body: the bodies legitimately differ in
    # the sticky email value echoed back into the form.
    assert _error(wrong_password) == _error(unknown_email)
    assert _error(wrong_password) == "Incorrect email or password."


def test_the_failure_message_is_defined_once(client):
    # The in-process equivalent of `grep -c`. @app.route returns the function
    # unmodified, so getsource() reads the real body.
    source = inspect.getsource(app_module.login)
    assert source.count('"Incorrect email or password."') == 1


def test_blank_email_is_rejected(client):
    _create_user()
    response = _login(client, email="   ")
    assert response.status_code == 200
    assert MISSING_FIELDS in response.data
    assert _session(client) == {}


def test_blank_password_is_rejected(client):
    _create_user()
    response = _login(client, password="")
    assert response.status_code == 200
    assert MISSING_FIELDS in response.data
    assert _session(client) == {}


def test_failed_login_repopulates_email_but_not_password(client):
    _create_user()
    response = _login(client, password="not-the-password")
    body = response.data.decode()
    assert 'value="grace@example.com"' in body
    assert "not-the-password" not in body


def test_failed_login_shows_no_success_banner(client):
    # Guards the easy regression of threading `registered` / `logged_out`
    # through the POST failure render "helpfully".
    _create_user()
    response = _login(client, password="not-the-password")
    assert b"auth-success" not in response.data


# ------------------------------------------------------------------ #
# Already signed in                                                   #
# ------------------------------------------------------------------ #

def test_get_login_while_signed_in_redirects_to_landing(client):
    # Pre-seeded rather than posted, so this does not depend on login working.
    _sign_in(client)
    response = client.get("/login")
    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def test_post_login_while_signed_in_does_not_touch_the_session(client):
    # The guard sits outside the method branch, so a signed-in POST cannot
    # re-authenticate as somebody else.
    _create_user()
    _sign_in(client, user_id=99, user_name="Someone Else")
    response = _login(client)
    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    assert _session(client) == {"user_id": 99, "user_name": "Someone Else"}


def test_get_register_while_signed_in_redirects_to_landing(client):
    _sign_in(client)
    response = client.get("/register")
    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def test_post_register_while_signed_in_creates_no_account(client):
    # A GET-only guard would leave this hole open: the form still submits.
    _sign_in(client)
    response = client.post(
        "/register",
        data={
            "name": "Interloper",
            "email": "interloper@example.com",
            "password": "longenough1",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    assert db.get_user_by_email("interloper@example.com") is None


# The signed-out control for this pair is
# test_get_login_still_renders_the_form, above.


# ------------------------------------------------------------------ #
# Logout                                                              #
# ------------------------------------------------------------------ #

def test_logout_redirects_to_login_with_flag(client):
    _sign_in(client)
    response = client.get("/logout")
    assert response.status_code == 302
    assert response.headers["Location"] == "/login?logged_out=1"


def test_logout_clears_the_session(client):
    _sign_in(client)
    client.get("/logout")
    assert _session(client) == {}


def test_logout_while_signed_out_is_harmless(client):
    # No pre-seed, and twice over: session.clear() on an empty session is a
    # no-op, so both calls must behave identically with no traceback.
    first = client.get("/logout")
    second = client.get("/logout")
    assert first.status_code == second.status_code == 302
    assert first.headers["Location"] == second.headers["Location"]
    assert _session(client) == {}


def test_logout_no_longer_returns_a_raw_string(client):
    response = client.get("/logout")
    assert response.status_code == 302
    assert b"coming in Step 3" not in response.data


# ------------------------------------------------------------------ #
# The signed-out banner                                               #
# ------------------------------------------------------------------ #

def test_login_shows_signed_out_banner(client):
    response = client.get("/login?logged_out=1")
    assert response.status_code == 200
    assert b"auth-success" in response.data
    assert b"You have been signed out." in response.data


def test_login_has_no_signed_out_banner_when_flag_is_zero(client):
    # request.args.get() yields the *string* "0", which Jinja treats as
    # truthy -- so a plain truthiness test in login() would show the banner
    # on a URL that means the opposite.
    response = client.get("/login?logged_out=0")
    assert response.status_code == 200
    assert b"You have been signed out." not in response.data


def test_login_has_no_banner_without_query_string(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b"auth-success" not in response.data


# ------------------------------------------------------------------ #
# The nav reflects the session                                        #
# ------------------------------------------------------------------ #

def test_nav_shows_anonymous_links_when_signed_out(client):
    # Safe to assert against / because landing.html contains none of these
    # strings itself -- its own CTA reads "Create free account".
    response = client.get("/")
    assert b"Sign in" in response.data
    assert b"Get started" in response.data
    assert b"Sign out" not in response.data
    assert b"nav-user" not in response.data


def test_nav_greets_the_user_when_signed_in(client):
    _sign_in(client)
    response = client.get("/")
    assert b"nav-user" in response.data
    assert USER["name"].encode() in response.data
    assert b"Sign out" in response.data
    assert b"Get started" not in response.data


def test_nav_state_persists_across_pages(client):
    _sign_in(client)
    for path in ("/", "/terms", "/privacy"):
        response = client.get(path)
        assert response.status_code == 200
        assert b"Sign out" in response.data


def test_sign_out_link_resolves_through_url_for(app):
    # Rendered HTML cannot tell url_for('logout') from a hardcoded /logout,
    # so this reads the template source instead.
    source = _source(app, "base.html")
    assert "url_for('logout')" in source
    assert 'href="/logout"' not in source


def test_sign_out_link_keeps_its_mobile_exemption(app):
    # The @media (max-width: 600px) rule hides .nav-links anchors that carry
    # neither .nav-cta nor .nav-signout. Drop this class and sign-out silently
    # becomes unreachable below 600px -- invisible to every other test here,
    # because the CSS itself is not exercised.
    source = _source(app, "base.html")
    assert "nav-signout" in source


# ------------------------------------------------------------------ #
# House rules                                                         #
# ------------------------------------------------------------------ #

def test_secret_key_is_set_at_import_time(client):
    # Read from the module, not the `app` fixture: the point is that the key
    # exists at import, not that a fixture could set one.
    assert app_module.app.secret_key


def test_secret_key_is_stable_rather_than_random(client):
    # A key from os.urandom() would be truthy and pass the test above while
    # invalidating every open session on each reloader restart.
    expected = os.environ.get(
        "SPENDLY_SECRET_KEY", "dev-only-not-for-production"
    )
    assert app_module.app.secret_key == expected


def test_auth_routes_contain_no_sql(client):
    for route in (app_module.login, app_module.logout):
        source = inspect.getsource(route)
        for keyword in ("SELECT", "INSERT", "UPDATE", "DELETE", "get_db("):
            assert keyword not in source
