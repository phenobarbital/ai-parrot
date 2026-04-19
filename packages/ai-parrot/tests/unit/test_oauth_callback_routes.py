"""Unit tests for the Jira OAuth callback route (TASK-752, FEAT-107)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot.auth.jira_oauth import JiraOAuthManager, JiraTokenSet
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
        manager.handle_callback = AsyncMock(
            return_value=(token_set, {"channel": "telegram", "user_id": "u1", "extra": {}})
        )
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
        manager.handle_callback = AsyncMock(
            return_value=(malicious, {"channel": "api", "user_id": "u1", "extra": {}})
        )
        app = _make_app(manager)
        client = await aiohttp_client(app)

        resp = await client.get("/api/auth/jira/callback?code=x&state=y")

        assert resp.status == 200
        text = await resp.text()
        assert "<script>alert(1)</script>" not in text
        assert "<img src=x>" not in text

    async def test_notifier_called_when_chat_id_present(self, aiohttp_client) -> None:
        token = JiraTokenSet(
            access_token="at",
            refresh_token="rt",
            expires_at=9999999999,
            cloud_id="c",
            site_url="https://test.atlassian.net",
            account_id="a",
            display_name="Test User",
        )
        state_payload = {
            "channel": "telegram",
            "user_id": "12345",
            "extra": {"chat_id": 99887766},
        }

        mock_manager = MagicMock()
        mock_manager.handle_callback = AsyncMock(return_value=(token, state_payload))

        mock_notifier = MagicMock()
        mock_notifier.notify_connected = AsyncMock()

        app = web.Application()
        app["jira_oauth_manager"] = mock_manager
        app["jira_oauth_notifier"] = mock_notifier
        setup_jira_oauth_routes(app)

        client = await aiohttp_client(app)
        resp = await client.get("/api/auth/jira/callback?code=x&state=y")

        assert resp.status == 200
        # Yield control so the fire-and-forget create_task runs to completion.
        await asyncio.sleep(0)
        mock_notifier.notify_connected.assert_awaited_once_with(
            99887766, "Test User", "https://test.atlassian.net"
        )

    def _count_callback_routes(self, app: web.Application) -> int:
        # aiohttp's add_get adds both a GET and a HEAD route for the same
        # resource by default; count only GET to detect actual duplicates.
        return sum(
            1
            for r in app.router.routes()
            if getattr(r.resource, "canonical", None) == "/api/auth/jira/callback"
            and r.method == "GET"
        )

    def test_manager_setup_mounts_route_and_signals(self) -> None:
        mock_redis = MagicMock()
        app = web.Application()
        mgr = JiraOAuthManager(
            client_id="x",
            client_secret="y",
            redirect_uri="https://h/cb",
            app=app,
            redis_client=mock_redis,
        )
        mgr.setup()

        assert app["jira_oauth_manager"] is mgr
        assert self._count_callback_routes(app) == 1
        assert mgr._on_startup in app.on_startup
        assert mgr._on_cleanup in app.on_cleanup

    def test_setup_is_idempotent(self) -> None:
        mock_redis = MagicMock()
        app = web.Application()
        mgr = JiraOAuthManager(
            client_id="x",
            client_secret="y",
            redirect_uri="https://h/cb",
            app=app,
            redis_client=mock_redis,
        )
        mgr.setup()
        mgr.setup()  # no-op

        assert self._count_callback_routes(app) == 1
        assert app.on_startup.count(mgr._on_startup) == 1
        assert app.on_cleanup.count(mgr._on_cleanup) == 1

    def test_setup_rejects_conflicting_existing_manager(self) -> None:
        mock_redis = MagicMock()
        app = web.Application()
        app["jira_oauth_manager"] = object()  # different instance
        mgr = JiraOAuthManager(
            client_id="x",
            client_secret="y",
            redirect_uri="https://h/cb",
            app=app,
            redis_client=mock_redis,
        )
        with pytest.raises(RuntimeError, match="already set"):
            mgr.setup()

    def test_setup_without_app_raises(self) -> None:
        mock_redis = MagicMock()
        mgr = JiraOAuthManager(
            client_id="x",
            client_secret="y",
            redirect_uri="https://h/cb",
            redis_client=mock_redis,
        )
        with pytest.raises(RuntimeError, match="app="):
            mgr.setup()

    async def test_notifier_not_called_when_no_chat_id(self, aiohttp_client) -> None:
        token = JiraTokenSet(
            access_token="at",
            refresh_token="rt",
            expires_at=9999999999,
            cloud_id="c",
            site_url="https://test.atlassian.net",
            account_id="a",
            display_name="Test User",
        )
        # extra has no chat_id (e.g., web UI flow)
        state_payload = {"channel": "api", "user_id": "u1", "extra": {}}

        mock_manager = MagicMock()
        mock_manager.handle_callback = AsyncMock(return_value=(token, state_payload))
        mock_notifier = MagicMock()
        mock_notifier.notify_connected = AsyncMock()

        app = web.Application()
        app["jira_oauth_manager"] = mock_manager
        app["jira_oauth_notifier"] = mock_notifier
        setup_jira_oauth_routes(app)

        client = await aiohttp_client(app)
        resp = await client.get("/api/auth/jira/callback?code=x&state=y")

        assert resp.status == 200
        # Yield control so the fire-and-forget create_task runs to completion.
        await asyncio.sleep(0)
        mock_notifier.notify_connected.assert_not_awaited()
