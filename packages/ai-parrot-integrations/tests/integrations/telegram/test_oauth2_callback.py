"""Tests for OAuth2 callback endpoint (TASK-246)."""

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from parrot.integrations.telegram.oauth2_callback import setup_oauth2_routes


def _create_app() -> web.Application:
    """Create a minimal aiohttp app with the OAuth2 callback route."""
    app = web.Application()
    setup_oauth2_routes(app)
    return app


@pytest.fixture
async def client():
    """Create a test client for the OAuth2 callback app."""
    app = _create_app()
    async with TestClient(TestServer(app)) as c:
        yield c


class TestOAuth2CallbackHandler:
    """Tests for oauth2_callback_handler."""

    @pytest.mark.asyncio
    async def test_success_with_code_and_state(self, client):
        resp = await client.get(
            "/oauth2/callback?code=auth_code_123&state=random_state_456"
        )
        assert resp.status == 200
        text = await resp.text()
        assert "sendData" in text
        assert "auth_code_123" in text
        assert "random_state_456" in text
        assert "telegram-web-app.js" in text

    @pytest.mark.asyncio
    async def test_success_includes_provider(self, client):
        resp = await client.get(
            "/oauth2/callback?code=abc&state=xyz&provider=github"
        )
        assert resp.status == 200
        text = await resp.text()
        assert "github" in text

    @pytest.mark.asyncio
    async def test_default_provider_is_google(self, client):
        resp = await client.get("/oauth2/callback?code=abc&state=xyz")
        assert resp.status == 200
        text = await resp.text()
        assert "google" in text

    @pytest.mark.asyncio
    async def test_missing_code_returns_400(self, client):
        resp = await client.get("/oauth2/callback?state=xyz")
        assert resp.status == 400
        text = await resp.text()
        assert "missing authorization code" in text.lower()

    @pytest.mark.asyncio
    async def test_missing_state_returns_400(self, client):
        resp = await client.get("/oauth2/callback?code=abc")
        assert resp.status == 400
        text = await resp.text()
        assert "missing state" in text.lower()

    @pytest.mark.asyncio
    async def test_no_params_returns_400(self, client):
        resp = await client.get("/oauth2/callback")
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_provider_error_returns_200_with_error(self, client):
        resp = await client.get(
            "/oauth2/callback?error=access_denied"
            "&error_description=User+denied+access"
        )
        assert resp.status == 200
        text = await resp.text()
        assert "User denied access" in text
        assert "sendData" not in text

    @pytest.mark.asyncio
    async def test_html_content_type(self, client):
        resp = await client.get("/oauth2/callback?code=abc&state=xyz")
        assert "text/html" in resp.headers.get("Content-Type", "")

    @pytest.mark.asyncio
    async def test_webapp_close_in_success(self, client):
        resp = await client.get("/oauth2/callback?code=abc&state=xyz")
        text = await resp.text()
        assert "WebApp.close()" in text

    @pytest.mark.asyncio
    async def test_webapp_close_in_error(self, client):
        resp = await client.get("/oauth2/callback?error=server_error")
        text = await resp.text()
        assert "WebApp.close()" in text

    @pytest.mark.asyncio
    async def test_special_chars_in_code_escaped(self, client):
        """Ensure code with special chars is JSON-escaped to prevent XSS."""
        resp = await client.get(
            '/oauth2/callback?code=<script>alert(1)</script>&state=safe'
        )
        assert resp.status == 200
        text = await resp.text()
        # Should be JSON-escaped, not raw HTML
        assert "<script>alert(1)</script>" not in text
        assert "\\u003cscript\\u003e" in text or "&lt;script&gt;" in text or "\\u003c" in text

    @pytest.mark.asyncio
    async def test_xss_in_error_description_escaped(self, client):
        """Ensure error_description is HTML-escaped to prevent XSS."""
        resp = await client.get(
            '/oauth2/callback?error=bad&error_description='
            '<script>alert(document.cookie)</script>'
        )
        assert resp.status == 200
        text = await resp.text()
        # Raw script tag must NOT appear in the HTML
        assert "<script>alert(document.cookie)</script>" not in text
        # Should be HTML-escaped
        assert "&lt;script&gt;" in text


class TestSetupOAuth2Routes:
    """Tests for route registration."""

    def test_registers_get_route(self):
        app = web.Application()
        setup_oauth2_routes(app)
        routes = [
            r.resource.canonical
            for r in app.router.routes()
            if hasattr(r, "resource") and r.resource
        ]
        assert "/oauth2/callback" in routes

    def test_custom_path(self):
        app = web.Application()
        setup_oauth2_routes(app, path="/auth/google/callback")
        routes = [
            r.resource.canonical
            for r in app.router.routes()
            if hasattr(r, "resource") and r.resource
        ]
        assert "/auth/google/callback" in routes
