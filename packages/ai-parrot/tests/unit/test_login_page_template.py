"""Static-content sanity tests for the login-page template
(FEAT-108 / TASK-762).

This template is served to Telegram WebApps and must preserve the
redirect-chain behavior added in this feature:

* Read ``next_auth_url`` / ``next_auth_required`` from the query string.
* Validate the redirect target (https:// only) before jumping.
* Fall back to ``Telegram.WebApp.sendData`` when no redirect is set.

A full JS test framework is not configured here; these tests lock in
the presence of the behavioral markers so regressions don't slip
through silently.
"""
from pathlib import Path

import pytest


LOGIN_PAGE = (
    Path(__file__).parents[2]
    / "src" / "parrot" / "integrations" / "telegram"
    / "static" / "login.html"
)


@pytest.fixture(scope="module")
def login_html() -> str:
    assert LOGIN_PAGE.exists(), f"login.html missing at {LOGIN_PAGE}"
    return LOGIN_PAGE.read_text(encoding="utf-8")


def test_reads_next_auth_url_param(login_html):
    assert "next_auth_url" in login_html


def test_reads_next_auth_required_param(login_html):
    assert "next_auth_required" in login_html


def test_has_webapp_senddata_fallback(login_html):
    assert "sendData" in login_html
    assert "Telegram.WebApp" in login_html or "tg.sendData" in login_html


def test_validates_https_redirect(login_html):
    # Safe-redirect guard against javascript: / data: / relative URLs.
    assert "isSafeRedirect" in login_html
    assert "https:" in login_html


def test_uses_window_location_href_for_redirect(login_html):
    assert "window.location.href" in login_html


def test_has_form_with_username_password(login_html):
    assert 'id="username"' in login_html
    assert 'id="password"' in login_html
    assert '<form' in login_html


def test_does_not_leak_credentials_through_url(login_html):
    """The redirect target must not have credentials appended to it."""
    # We redirect to nextAuthUrl verbatim — no `?basic_auth=...` tacked on.
    assert "?basic_auth=" not in login_html
    assert "&basic_auth=" not in login_html
    assert "payload=" not in login_html


def test_posts_to_auth_url(login_html):
    assert "fetch(authUrl" in login_html
    assert "'POST'" in login_html or '"POST"' in login_html
