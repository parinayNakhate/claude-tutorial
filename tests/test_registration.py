"""Tests for Step 2 -- user registration."""

import os

from werkzeug.security import check_password_hash

import database.db as db

VALID = {
    "name": "Ada Lovelace",
    "email": "ada@example.com",
    "password": "analytical1",
}


def _users():
    """Every users row, as a list. Opens and closes its own connection."""
    conn = db.get_db()
    try:
        return conn.execute("SELECT * FROM users ORDER BY id").fetchall()
    finally:
        conn.close()


def _register(client, **overrides):
    """POST the valid payload with `overrides` applied."""
    return client.post("/register", data=dict(VALID, **overrides))


def _source(app, template):
    """The raw template source, before Jinja renders it."""
    return app.jinja_env.loader.get_source(app.jinja_env, template)[0]


# ------------------------------------------------------------------ #
# The route responds at all                                           #
# ------------------------------------------------------------------ #

def test_get_register_returns_200(client):
    response = client.get("/register")
    assert response.status_code == 200
    assert b"Create your account" in response.data


def test_post_register_is_no_longer_405(client):
    response = _register(client)
    assert response.status_code != 405
    assert response.status_code == 302


# ------------------------------------------------------------------ #
# The happy path                                                      #
# ------------------------------------------------------------------ #

def test_successful_registration_inserts_exactly_one_row(client):
    _register(client)
    rows = _users()
    assert len(rows) == 1
    assert rows[0]["name"] == "Ada Lovelace"
    assert rows[0]["email"] == "ada@example.com"


def test_successful_registration_redirects_to_login_with_flag(client):
    response = _register(client)
    assert response.status_code == 302
    # Werkzeug 3.x emits a relative Location, not an absolute URL.
    assert response.headers["Location"] == "/login?registered=1"


def test_login_shows_success_banner_when_registered(client):
    response = client.get("/login?registered=1")
    assert response.status_code == 200
    assert b"auth-success" in response.data
    assert b"Account created." in response.data


def test_login_has_no_banner_without_query_string(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b"auth-success" not in response.data


def test_login_has_no_banner_when_registered_is_zero(client):
    # request.args.get() yields the *string* "0", which Jinja treats as
    # truthy -- so a plain truthiness test in login() would show the banner
    # on a URL that means the opposite.
    response = client.get("/login?registered=0")
    assert response.status_code == 200
    assert b"auth-success" not in response.data


# ------------------------------------------------------------------ #
# Email normalisation                                                 #
# ------------------------------------------------------------------ #

def test_email_is_stored_lowercased(client):
    _register(client, email="Foo@Example.COM")
    assert _users()[0]["email"] == "foo@example.com"


def test_email_is_stored_stripped(client):
    _register(client, email="  x@y.com  ")
    assert _users()[0]["email"] == "x@y.com"


# ------------------------------------------------------------------ #
# Validation rejections                                               #
# ------------------------------------------------------------------ #

def test_duplicate_email_differing_only_in_case_is_rejected(client):
    _register(client)
    response = _register(client, email="ADA@Example.com")
    assert response.status_code == 200
    assert b"An account with that email already exists." in response.data
    assert len(_users()) == 1


def test_short_password_is_rejected(client):
    response = _register(client, password="1234567")
    assert response.status_code == 200
    assert b"Password must be at least 8 characters." in response.data
    assert _users() == []


def test_blank_name_is_rejected(client):
    response = _register(client, name="   ")
    assert response.status_code == 200
    assert b"All fields are required." in response.data
    assert _users() == []


def test_invalid_email_is_rejected(client):
    response = _register(client, email="not-an-email")
    assert response.status_code == 200
    assert b"Enter a valid email address." in response.data
    assert _users() == []


# ------------------------------------------------------------------ #
# Password handling and form behaviour                                #
# ------------------------------------------------------------------ #

def test_password_is_hashed_not_stored_plaintext(client):
    _register(client)
    stored = _users()[0]["password_hash"]
    assert stored != VALID["password"]
    # scrypt (werkzeug's default) raises AttributeError on this Python build.
    assert stored.startswith("pbkdf2:sha256")
    assert check_password_hash(stored, VALID["password"])


def test_form_repopulates_name_and_email_but_not_password(client):
    response = _register(client, password="short")
    body = response.data.decode()
    assert 'value="Ada Lovelace"' in body
    assert 'value="ada@example.com"' in body
    assert "short" not in body


def test_form_actions_resolve_through_url_for(app):
    # The rendered HTML cannot distinguish these: url_for('register') emits
    # exactly "/register". Only the template source shows which was written.
    for template, endpoint in (("register.html", "register"),
                               ("login.html", "login")):
        source = _source(app, template)
        assert "url_for('%s')" % endpoint in source
        assert 'action="/%s"' % endpoint not in source


# ------------------------------------------------------------------ #
# Nothing else moved                                                  #
# ------------------------------------------------------------------ #

def test_stub_routes_are_untouched(client):
    expected = {
        "/logout": "Logout — coming in Step 3",
        "/profile": "Profile page — coming in Step 4",
        "/expenses/add": "Add expense — coming in Step 7",
        "/expenses/1/edit": "Edit expense — coming in Step 8",
        "/expenses/1/delete": "Delete expense — coming in Step 9",
    }
    for path, body in expected.items():
        response = client.get(path)
        assert response.status_code == 200
        assert response.data.decode() == body


def test_suite_does_not_touch_the_project_database():
    assert db.DB_PATH != os.path.join(db.BASE_DIR, "spendly.db")
