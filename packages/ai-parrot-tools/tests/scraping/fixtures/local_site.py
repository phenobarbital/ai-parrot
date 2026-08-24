"""``local_fixture_site`` — a real, locally-bound HTTP server for FEAT-455's
real-browser integration tests (FEAT-453 spec's own Test Data section
named this fixture; no task ever built it until now).

Serves five deterministic, self-contained routes — login, a session-gated
dashboard, a file upload target, a file download target, and a cookie
echo page — via a real ``aiohttp.web.Application`` bound to a real local
port through the ``aiohttp_server`` pytest-aiohttp fixture (the same
pattern already proven in ``tests/rss/test_fetcher.py``/``test_toolkit.py``).

Anonymized-fixtures convention (FEAT-453): every rendered string uses a
generic "acme-books" brand — never a real product/vendor name. No route
here ever contacts, proxies, or redirects to a third-party host.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from aiohttp import web

if TYPE_CHECKING:
    from aiohttp.test_utils import TestServer

#: The one hardcoded test credential this fixture accepts — never a real
#: secret, this is a self-contained local test server.
TEST_USERNAME = "testuser"
TEST_PASSWORD = "testpass123"

#: Name of the cookie issued on a successful /login.
SESSION_COOKIE_NAME = "acme_session"

#: Deterministic, byte-exact download content (never randomly generated —
#: downstream tests assert exact-match content across repeated requests).
DOWNLOAD_CONTENT = b"%PDF-1.4\nacme-books fixture report\n" + b"0" * 1024

_LOGIN_FORM = """\
<html><body>
<h1>acme-books — Sign in</h1>
{error}
<form method="post" action="/login">
  <input type="text" id="username" name="username" />
  <input type="password" id="password" name="password" />
  <button type="submit">Sign in</button>
</form>
</body></html>
"""


def _render_login(error: str = "") -> str:
    error_html = f'<p class="error">Error: {error}</p>' if error else ""
    return _LOGIN_FORM.format(error=error_html)


async def _handle_login_get(request: web.Request) -> web.Response:
    return web.Response(text=_render_login(), content_type="text/html")


async def _handle_login_post(request: web.Request) -> web.Response:
    data = await request.post()
    username = data.get("username", "")
    password = data.get("password", "")

    if username != TEST_USERNAME or password != TEST_PASSWORD:
        return web.Response(
            text=_render_login(error="invalid username or password"),
            content_type="text/html",
        )

    token = uuid.uuid4().hex
    request.app["sessions"][token] = username

    resp = web.HTTPFound("/dashboard")
    resp.set_cookie(SESSION_COOKIE_NAME, token, path="/")
    return resp


async def _handle_dashboard(request: web.Request) -> web.Response:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    username = request.app["sessions"].get(token) if token else None
    if username is None:
        return web.Response(text="Unauthorized", status=401)
    return web.Response(
        text=f"<html><body><h1>acme-books dashboard</h1><p>Welcome, {username}</p></body></html>",
        content_type="text/html",
    )


async def _handle_upload(request: web.Request) -> web.Response:
    data = await request.post()
    field = data.get("file")
    if field is None or not hasattr(field, "file"):
        return web.Response(text="No file field named 'file'", status=400)

    content = field.file.read()
    return web.json_response({"filename": field.filename, "bytes": len(content)})


async def _handle_download(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    return web.Response(
        body=DOWNLOAD_CONTENT,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
        content_type="application/octet-stream",
    )


async def _handle_cookie_check(request: web.Request) -> web.Response:
    return web.Response(text=request.headers.get("Cookie", ""))


def build_app() -> web.Application:
    """Build the acme-books fixture site's ``web.Application``.

    Session state is a plain in-memory dict on the app itself
    (``app["sessions"]``) — this is a test fixture, not production code,
    so no real session-store abstraction is warranted.
    """
    app = web.Application()
    app["sessions"] = {}
    app.router.add_get("/login", _handle_login_get)
    app.router.add_post("/login", _handle_login_post)
    app.router.add_get("/dashboard", _handle_dashboard)
    app.router.add_post("/upload", _handle_upload)
    app.router.add_get("/download/{name}", _handle_download)
    app.router.add_get("/cookie-check", _handle_cookie_check)
    return app


@pytest.fixture
async def local_fixture_site(aiohttp_server) -> TestServer:
    """Real local HTTP server: ``/login``, ``/dashboard``, ``/upload``,
    ``/download/<name>``, ``/cookie-check``.

    A real pytest fixture, importable directly into a test module's
    namespace (matching this package's existing relative-import
    convention for shared test helpers, e.g.
    ``tests/business_automation/test_submit_gate.py``'s
    ``from .conftest import SpyConfirmationGuard``) — pytest resolves a
    fixture by name in the test module's globals, so
    ``from .fixtures.local_site import local_fixture_site`` in a sibling
    test file is sufficient; no ``conftest.py`` registration is needed.

    Returns:
        The bound ``aiohttp.test_utils.TestServer`` — use
        ``server.make_url(path)`` for a real, connectable URL.
    """
    app = build_app()
    return await aiohttp_server(app)
