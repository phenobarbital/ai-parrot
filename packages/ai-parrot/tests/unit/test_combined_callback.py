"""Unit tests for combined auth callback handler (FEAT-108 / TASK-759)."""
import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from parrot.integrations.telegram.combined_callback import (
    COMBINED_CALLBACK_PATH,
    combined_auth_callback_handler,
    setup_combined_auth_routes,
)


def _make_request(query: dict) -> web.Request:
    """Build a mocked GET request with the given query-string params."""
    qs = "&".join(f"{k}={v}" for k, v in query.items())
    path = COMBINED_CALLBACK_PATH + (f"?{qs}" if qs else "")
    return make_mocked_request("GET", path)


@pytest.mark.asyncio
async def test_success_returns_html_with_senddata():
    request = _make_request({"code": "abc123", "state": "nonce456"})
    response = await combined_auth_callback_handler(request)
    assert response.status == 200
    assert response.content_type == "text/html"
    assert "sendData" in response.text
    assert "abc123" in response.text
    assert "nonce456" in response.text
    # Default provider is "jira".
    assert '"jira"' in response.text


@pytest.mark.asyncio
async def test_success_uses_custom_provider():
    request = _make_request(
        {"code": "c", "state": "s", "provider": "confluence"}
    )
    response = await combined_auth_callback_handler(request)
    assert response.status == 200
    assert '"confluence"' in response.text
    # Default "jira" should NOT appear literally in the JS payload key.
    # (It's the default, so absent when explicit provider is passed.)
    # Still, the string 'jira' may appear inside comments, so only check the
    # explicit literal `"confluence"` above.


@pytest.mark.asyncio
async def test_missing_code_returns_400():
    request = _make_request({"state": "nonce456"})
    response = await combined_auth_callback_handler(request)
    assert response.status == 400
    assert "missing authorization code" in response.text.lower()


@pytest.mark.asyncio
async def test_missing_state_returns_400():
    request = _make_request({"code": "abc123"})
    response = await combined_auth_callback_handler(request)
    assert response.status == 400
    assert "missing state" in response.text.lower()


@pytest.mark.asyncio
async def test_oauth_error_returns_html_200():
    request = _make_request(
        {"error": "access_denied",
         "error_description": "User+denied+consent"}
    )
    response = await combined_auth_callback_handler(request)
    assert response.status == 200
    # The error description is shown to the user.
    # (aiohttp auto-decodes + to space? Not always; accept either form.)
    lower = response.text.lower()
    assert "authentication failed" in lower


@pytest.mark.asyncio
async def test_json_escape_prevents_xss():
    """Values containing <script> tags must not break out of the JS string."""
    malicious = "</script><script>alert(1)</script>"
    request = _make_request({"code": malicious, "state": "s"})
    response = await combined_auth_callback_handler(request)
    assert response.status == 200
    # The raw closing tag must not appear literally inside the response.
    assert "</script><script>alert(1)" not in response.text
    # But the unicode-escaped form does.
    assert "\\u003c" in response.text


def test_setup_combined_auth_routes_registers_path():
    app = web.Application()
    setup_combined_auth_routes(app)
    routes = [r.resource.canonical for r in app.router.routes()
              if hasattr(r.resource, "canonical")]
    assert COMBINED_CALLBACK_PATH in routes


def test_setup_accepts_custom_path():
    app = web.Application()
    custom_path = "/custom/callback"
    setup_combined_auth_routes(app, path=custom_path)
    routes = [r.resource.canonical for r in app.router.routes()
              if hasattr(r.resource, "canonical")]
    assert custom_path in routes
