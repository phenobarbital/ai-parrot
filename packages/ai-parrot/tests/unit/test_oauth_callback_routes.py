"""Unit tests for the Jira OAuth callback route (TASK-752, FEAT-107)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot.auth.jira_oauth import JiraTokenSet
from parrot.auth.routes import setup_jira_oauth_routes


def _make_app(manager) -> web.Application:
    app = web.Application()
    app["jira_oauth_manager"] = manager
    setup_jira_oauth_routes(app)
    return app


@pytest.fixture
def token_set() -> JiraTokenSet:
    return JiraTokenSet(
        access_token="at",
        refresh_token="rt",
        expires_at=9999999999,
        cloud_id="c",
        site_url="https://test.atlassian.net",
        account_id="a",
        display_name="Test User",
    )


class TestJiraOAuthCallback:
    async def test_missing_code_returns_400(self, aiohttp_client) -> None:
        app = _make_app(MagicMock())
        client = await aiohttp_client(app)
        resp = await client.get("/api/auth/jira/callback?state=abc")
        assert resp.status == 400
        text = await resp.text()
        assert "Missing code or state" in text

    async def test_missing_state_returns_400(self, aiohttp_client) -> None:
        app = _make_app(MagicMock())
        client = await aiohttp_client(app)
        resp = await client.get("/api/auth/jira/callback?code=abc")
        assert resp.status == 400

    async def test_valid_callback_renders_success(
        self, aiohttp_client, token_set: JiraTokenSet
    ) -> None:
        manager = MagicMock()
        manager.handle_callback = AsyncMock(return_value=token_set)
        app = _make_app(manager)
        client = await aiohttp_client(app)

        resp = await client.get("/api/auth/jira/callback?code=x&state=y")

        assert resp.status == 200
        text = await resp.text()
        assert "Test User" in text
        assert "test.atlassian.net" in text
        manager.handle_callback.assert_awaited_once_with("x", "y")

    async def test_invalid_state_returns_400(self, aiohttp_client) -> None:
        manager = MagicMock()
        manager.handle_callback = AsyncMock(
            side_effect=ValueError("Invalid or expired state nonce."),
        )
        app = _make_app(manager)
        client = await aiohttp_client(app)

        resp = await client.get("/api/auth/jira/callback?code=x&state=bad")

        assert resp.status == 400
        text = await resp.text()
        assert "Invalid or expired state nonce" in text

    async def test_unexpected_error_returns_500(self, aiohttp_client) -> None:
        manager = MagicMock()
        manager.handle_callback = AsyncMock(side_effect=RuntimeError("boom"))
        app = _make_app(manager)
        client = await aiohttp_client(app)

        resp = await client.get("/api/auth/jira/callback?code=x&state=y")

        assert resp.status == 500

    async def test_manager_not_configured_returns_500(self, aiohttp_client) -> None:
        # Intentionally do NOT register ``jira_oauth_manager``.
        app = web.Application()
        setup_jira_oauth_routes(app)
        client = await aiohttp_client(app)

        resp = await client.get("/api/auth/jira/callback?code=x&state=y")

        assert resp.status == 500

    async def test_html_escapes_user_content(
        self, aiohttp_client
    ) -> None:
        malicious = JiraTokenSet(
            access_token="at",
            refresh_token="rt",
            expires_at=9999999999,
            cloud_id="c",
            site_url='"><script>alert(1)</script>',
            account_id="a",
            display_name='<img src=x>',
        )
        manager = MagicMock()
        manager.handle_callback = AsyncMock(return_value=malicious)
        app = _make_app(manager)
        client = await aiohttp_client(app)

        resp = await client.get("/api/auth/jira/callback?code=x&state=y")

        assert resp.status == 200
        text = await resp.text()
        assert "<script>alert(1)</script>" not in text
        assert "<img src=x>" not in text
