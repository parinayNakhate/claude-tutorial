"""Tests for Step 4 -- the profile page design pass.

The page is deliberately static: it renders hardcoded constants from app.py,
not the database. So these tests assert on layout, the access gate and the
shape of the data, and they never seed a user. conftest.py's autouse
clean_tables fixture empties both tables before every test anyway -- which is
exactly why _sign_in() fakes the session cookie instead of posting the form.
"""

import inspect
import re

import app as app_module

NAME = "Grace Hopper"


def _sign_in(client, user_id=1, user_name=NAME):
    """Put a signed-in session in the client's cookie jar without a POST.

    Same helper as tests/test_login.py: session_transaction() re-signs the
    session on exit, so the next request arrives already authenticated.
    """
    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["user_name"] = user_name


def _session(client):
    """The client's session as a plain dict."""
    with client.session_transaction() as session:
        return dict(session)


def _source(app, template):
    """The raw template source, before Jinja renders it."""
    return app.jinja_env.loader.get_source(app.jinja_env, template)[0]


def _profile(client, **kwargs):
    """Sign in and fetch /profile."""
    _sign_in(client, **kwargs)
    return client.get("/profile")


# ------------------------------------------------------------------ #
# The access gate                                                     #
# ------------------------------------------------------------------ #

def test_anonymous_visitor_is_redirected_to_login(client):
    response = client.get("/profile")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_anonymous_visitor_never_sees_the_page_body(client):
    """The redirect must not carry the content it is supposed to be gating."""
    body = client.get("/profile").data
    assert b"profile-card" not in body
    assert b"Recent transactions" not in body


def test_signed_in_visitor_gets_the_page(client):
    assert _profile(client).status_code == 200


def test_the_gate_does_not_touch_the_session(client):
    """Reading /profile must not write, clear or rotate anything."""
    _sign_in(client)
    client.get("/profile")
    assert _session(client) == {"user_id": 1, "user_name": NAME}


# ------------------------------------------------------------------ #
# Section 1 -- identity                                               #
# ------------------------------------------------------------------ #

def test_the_page_shows_the_signed_in_users_name(client):
    """The name is the one live value on an otherwise static page."""
    body = _profile(client, user_name="Ada Lovelace").data
    assert b"Ada Lovelace" in body


def test_the_avatar_shows_the_users_initials(client):
    body = _profile(client, user_name="Ada Lovelace").data.decode()
    assert re.search(r'class="profile-avatar"[^>]*>\s*AL\s*<', body)


def test_a_single_word_name_does_not_break_the_avatar(client):
    """parts[-1][0] would still work, but parts[0][0] is the whole name."""
    response = _profile(client, user_name="Ada")
    assert response.status_code == 200
    assert re.search(
        r'class="profile-avatar"[^>]*>\s*A\s*<', response.data.decode()
    )


def test_an_empty_name_falls_back_instead_of_raising(client):
    """A session can carry an empty name; a 500 here would be absurd."""
    response = _profile(client, user_name="")
    assert response.status_code == 200
    assert re.search(
        r'class="profile-avatar"[^>]*>\s*\?\s*<', response.data.decode()
    )


def test_the_page_shows_the_email_and_join_date(client):
    body = _profile(client).data
    assert app_module._PROFILE_EMAIL.encode() in body
    assert app_module._PROFILE_MEMBER_SINCE.encode() in body


# ------------------------------------------------------------------ #
# Section 2 -- summary stats                                          #
# ------------------------------------------------------------------ #

def test_all_three_summary_stats_render(client):
    body = _profile(client).data
    for label in (b"Total spent", b"Transactions", b"Top category"):
        assert label in body


def test_the_total_is_formatted_as_rupees_with_separators(client):
    body = _profile(client).data.decode()
    assert "₹6,484.00" in body


def test_the_transaction_count_matches_the_data(client):
    body = _profile(client).data.decode()
    count = app_module._PROFILE_SUMMARY["count"]
    assert ">{}<".format(count) in body.replace("\n", "").replace(" ", "")


def test_the_top_category_is_derived_not_hardcoded(client):
    """Editing _PROFILE_EXPENSES must not be able to leave this stat lying."""
    assert app_module._PROFILE_SUMMARY["top_category"] == "Shopping"
    assert b"Shopping" in _profile(client).data


# ------------------------------------------------------------------ #
# Section 3 -- transaction table                                      #
# ------------------------------------------------------------------ #

def test_every_transaction_gets_a_row(client):
    body = _profile(client).data.decode()
    rows = body.count('<td class="profile-col-date"')
    assert rows == len(app_module._PROFILE_EXPENSES)
    assert rows >= 3


def test_each_row_carries_its_description_and_amount(client):
    body = _profile(client).data.decode()
    for expense in app_module._PROFILE_EXPENSES:
        assert expense["description"] in body
        assert app_module.rupees(expense["amount"]) in body


def test_category_badges_use_a_class_never_an_inline_colour(client):
    """The spec is explicit: badge colour comes from CSS, not style=."""
    body = _profile(client).data.decode()
    badges = re.findall(r'class="profile-badge profile-badge-([a-z]+)"', body)
    assert len(set(badges)) >= 3
    for match in re.findall(r"<span[^>]*profile-badge[^>]*>", body):
        assert "style=" not in match


def test_badge_modifiers_match_the_categories_in_the_data(client):
    body = _profile(client).data.decode()
    for expense in app_module._PROFILE_EXPENSES:
        expected = "profile-badge-{}".format(expense["category"].lower())
        assert expected in body


# ------------------------------------------------------------------ #
# Section 4 -- category breakdown                                     #
# ------------------------------------------------------------------ #

def test_every_category_gets_a_bar(client):
    body = _profile(client).data.decode()
    bars = re.findall(r'class="profile-bar-fill [^"]*"\s*style="width: (\d+)%"', body)
    assert len(bars) == len(app_module._PROFILE_BREAKDOWN)
    assert len(bars) >= 3


def test_the_bar_percentages_cover_the_whole_total(client):
    body = _profile(client).data.decode()
    bars = re.findall(r'style="width: (\d+)%"', body)
    assert sum(int(width) for width in bars) == 100


def test_the_bars_are_ordered_largest_first(client):
    widths = [row["percent"] for row in app_module._PROFILE_BREAKDOWN]
    assert widths == sorted(widths, reverse=True)


def test_each_bar_is_labelled_for_screen_readers(client):
    """A bare coloured div tells a screen reader nothing."""
    body = _profile(client).data.decode()
    labels = re.findall(r'aria-label="([^"]+) percent of total spending"', body)
    assert len(labels) == len(app_module._PROFILE_BREAKDOWN)


def test_the_breakdown_totals_match_the_transactions(client):
    """The bars and the table must describe the same money."""
    assert sum(row["amount"] for row in app_module._PROFILE_BREAKDOWN) == sum(
        expense["amount"] for expense in app_module._PROFILE_EXPENSES
    )


# ------------------------------------------------------------------ #
# Money is rupees                                                     #
# ------------------------------------------------------------------ #

def test_the_rupees_filter_formats_with_separators_and_paise():
    assert app_module.rupees(6484.0) == "₹6,484.00"
    assert app_module.rupees(0) == "₹0.00"
    assert app_module.rupees(120.5) == "₹120.50"


def test_no_dollar_signs_reach_the_page(client):
    assert b"$" not in _profile(client).data


# ------------------------------------------------------------------ #
# Dates                                                               #
# ------------------------------------------------------------------ #

def test_the_day_filter_formats_stored_dates_for_humans():
    assert app_module.day("2026-08-25") == "25 Aug 2026"
    assert app_module.day("2026-08-03") == "3 Aug 2026"


def test_the_day_filter_falls_back_instead_of_raising():
    """A malformed date should spoil one cell, not the whole render."""
    assert app_module.day("not-a-date") == "not-a-date"
    assert app_module.day(None) is None


def test_the_table_shows_readable_dates_not_raw_timestamps(client):
    body = _profile(client).data.decode()
    assert "25 Aug 2026" in body
    # The ISO form survives only in the machine-readable attribute.
    assert ">2026-08-25<" not in body
    assert 'datetime="2026-08-25"' in body


# ------------------------------------------------------------------ #
# Empty states (unreachable now; they are Step 5's safety net)        #
# ------------------------------------------------------------------ #

def test_the_template_handles_having_no_transactions(client, app):
    rendered = app.jinja_env.get_template("profile.html").render(
        session={"user_id": 1, "user_name": NAME},
        email="x@example.com", member_since="January 2026",
        expenses=(), summary={"total": 0, "count": 0, "top_category": "-"},
        breakdown=(),
    )
    assert "No transactions yet." in rendered
    assert "Nothing to break down yet." in rendered
    assert "₹0.00" in rendered


# ------------------------------------------------------------------ #
# House rules                                                         #
# ------------------------------------------------------------------ #

def test_profile_contains_no_sql(client):
    """Step 4 is a design pass -- the view must not touch the database."""
    source = inspect.getsource(app_module.profile)
    for token in ("SELECT", "INSERT", "UPDATE", "DELETE", "get_db("):
        assert token not in source


def test_profile_template_has_no_hardcoded_urls(client, app):
    source = _source(app, "profile.html")
    assert 'href="/' not in source
    assert "url_for(" in source


def test_profile_template_has_no_hex_colours(client, app):
    """CLAUDE.md: use CSS variables, never hardcode hex values."""
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", _source(app, "profile.html"))


def test_profile_template_extends_base(client, app):
    assert '{% extends "base.html" %}' in _source(app, "profile.html")


def test_profile_css_is_page_scoped_not_global(client, app):
    """The stylesheet loads from profile.html, so no other page pays for it."""
    assert "css/profile.css" in _source(app, "profile.html")
    assert "css/profile.css" not in _source(app, "base.html")


def test_profile_page_has_no_inline_style_block(client, app):
    """Page styles belong in a .css file, not a <style> tag."""
    assert "<style" not in _source(app, "profile.html")


def test_the_only_inline_styles_are_bar_widths(client):
    """Width is data. Everything else must come from a class."""
    body = _profile(client).data.decode()
    for value in re.findall(r'style="([^"]*)"', body):
        assert re.match(r"^width: \d+%$", value), value


# ------------------------------------------------------------------ #
# Navigation                                                          #
# ------------------------------------------------------------------ #

def test_the_nav_greeting_links_to_the_profile(client):
    """Without this the page is unreachable except by typing the URL."""
    _sign_in(client)
    body = client.get("/").data.decode()
    assert re.search(r'<a href="/profile" class="nav-user">', body)


def test_the_nav_still_shows_the_signed_in_state_on_the_profile(client):
    body = _profile(client).data
    assert b"nav-user" in body
    assert b"Sign out" in body
    assert b"Get started" not in body


def test_the_mobile_nav_rule_does_not_hide_the_greeting(client):
    """.nav-user became an <a> in Step 4; the 600px rule must exempt it."""
    with open("static/css/style.css") as handle:
        css = handle.read()
    assert ".nav-links a:not(.nav-cta):not(.nav-signout):not(.nav-user)" in css


# ------------------------------------------------------------------ #
# Nothing else moved                                                  #
# ------------------------------------------------------------------ #

def test_profile_no_longer_returns_a_raw_string(client):
    """CLAUDE.md: no raw string returns once a step is implemented."""
    response = _profile(client)
    assert response.status_code == 200
    assert b"coming in Step 4" not in response.data
    assert b"<!DOCTYPE html>" in response.data


def test_the_expense_stubs_are_untouched(client):
    expected = {
        "/expenses/add": "Add expense — coming in Step 7",
        "/expenses/1/edit": "Edit expense — coming in Step 8",
        "/expenses/1/delete": "Delete expense — coming in Step 9",
    }
    for path, body in expected.items():
        response = client.get(path)
        assert response.status_code == 200
        assert response.data.decode() == body
