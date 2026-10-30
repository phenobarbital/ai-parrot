"""Unit tests for the Jira alias of the generic OAuth2 callback route."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from parrot.auth.jira_oauth import JiraOAuthManager, JiraTokenSet
from parrot.auth.routes import setup_jira_oauth_routes


def _make_app(manager: object) -> web.Application:
    app = web.Application()
    app["oauth2_manager_jira"] = manager
    setup_jira_oauth_routes(app)
    return app


async def _invoke_callback(app: web.Application, path: str) -> web.Response:
    """Invoke the GET callback registered on ``app`` without opening a socket."""
    route = next(
        route
        for route in app.router.routes()
        if route.method == "GET"
        and route.get_info().get("path") == "/api/auth/jira/callback"
    )
    request = make_mocked_request("GET", path, app=app)
    return await route.handler(request)


@pytest.fixture
def token_set() -> JiraTokenSet:
    """Return a representative Jira token set."""
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
    """Exercise Jira through the generic callback implementation."""

    @pytest.mark.asyncio
    async def test_jira_callback_alias_path(
        self,
        aiohttp_client,
        token_set: JiraTokenSet,
    ) -> None:
        import parrot.auth.routes as routes

        manager = MagicMock()
        manager.handle_callback = AsyncMock(
            return_value=(
                token_set,
                {
                    "channel": "telegram",
                    "nav_user_id": "42",
                    "canonical_identity": "user@example.com",
                },
            )
        )
        persist_credential = AsyncMock()
        app = _make_app(manager)

        with patch("parrot.auth.oauth2_routes.IntegrationsService") as service:
            service.return_value.persist_credential = persist_credential
            response = await _invoke_callback(
                app,
                "/api/auth/jira/callback?code=x&state=y",
            )

        assert response.status == 200
        assert not hasattr(routes, "jira_oauth_callback")
        manager.handle_callback.assert_awaited_once_with("x", "y")
        persist_credential.assert_awaited_once_with(
            "42",
            "jira",
            token_set,
            channel="telegram",
            canonical_identity="user@example.com",
        )

    async def test_missing_code_returns_400(self) -> None:
        app = _make_app(MagicMock())

        response = await _invoke_callback(
            app,
            "/api/auth/jira/callback?state=abc",
        )

        assert response.status == 400
        assert "Missing code or state" in response.text

    async def test_missing_state_returns_400(self) -> None:
        app = _make_app(MagicMock())

        response = await _invoke_callback(
            app,
            "/api/auth/jira/callback?code=abc",
        )

        assert response.status == 400

    async def test_invalid_state_returns_400(self) -> None:
        manager = MagicMock()
        manager.handle_callback = AsyncMock(side_effect=ValueError("Invalid state"))
        app = _make_app(manager)

        response = await _invoke_callback(
            app,
            "/api/auth/jira/callback?code=x&state=bad",
        )

        assert response.status == 400
        assert "Invalid or expired authorization request" in response.text

    async def test_unexpected_error_returns_500(self) -> None:
        manager = MagicMock()
        manager.handle_callback = AsyncMock(side_effect=RuntimeError("boom"))
        app = _make_app(manager)

        response = await _invoke_callback(
            app,
            "/api/auth/jira/callback?code=x&state=y",
        )

        assert response.status == 500

    async def test_manager_not_configured_returns_500(self) -> None:
        app = web.Application()
        setup_jira_oauth_routes(app)

        response = await _invoke_callback(
            app,
            "/api/auth/jira/callback?code=x&state=y",
        )

        assert response.status == 500

    async def test_provider_denial_consumes_nonce_and_writes_nothing(
        self,
    ) -> None:
        manager = MagicMock()
        manager.handle_callback = AsyncMock()
        manager._nonce_key.return_value = "oauth2:nonce:jira:nonce"
        manager.redis.delete = AsyncMock()
        app = _make_app(manager)

        with patch("parrot.auth.oauth2_routes.IntegrationsService") as service:
            response = await _invoke_callback(
                app,
                "/api/auth/jira/callback?error=access_denied&state=nonce"
            )

        assert response.status == 400
        assert "cancelled or denied" in response.text
        manager._nonce_key.assert_called_once_with("nonce")
        manager.redis.delete.assert_awaited_once_with("oauth2:nonce:jira:nonce")
        manager.handle_callback.assert_not_awaited()
        service.assert_not_called()

    async def test_provider_denial_nonce_delete_is_best_effort(
        self,
    ) -> None:
        manager = MagicMock()
        manager.handle_callback = AsyncMock()
        manager._nonce_key.return_value = "oauth2:nonce:jira:nonce"
        manager.redis.delete = AsyncMock(side_effect=RuntimeError("redis unavailable"))
        app = _make_app(manager)

        response = await _invoke_callback(
            app,
            "/api/auth/jira/callback?error=access_denied&state=nonce"
        )

        assert response.status == 400
        manager.handle_callback.assert_not_awaited()

    def _count_callback_routes(self, app: web.Application) -> int:
        return sum(
            1
            for route in app.router.routes()
            if getattr(route.resource, "canonical", None)
            == "/api/auth/jira/callback"
            and route.method == "GET"
        )

    def test_manager_setup_mounts_route_and_signals(self) -> None:
        app = web.Application()
        manager = JiraOAuthManager(
            client_id="x",
            client_secret="y",
            redirect_uri="https://h/cb",
            app=app,
            redis_client=MagicMock(),
        )

        manager.setup()

        assert app["jira_oauth_manager"] is manager
        assert app["oauth2_manager_jira"] is manager
        assert self._count_callback_routes(app) == 1
        assert manager._on_startup in app.on_startup
        assert manager._on_cleanup in app.on_cleanup

    def test_setup_is_idempotent(self) -> None:
        app = web.Application()
        manager = JiraOAuthManager(
            client_id="x",
            client_secret="y",
            redirect_uri="https://h/cb",
            app=app,
            redis_client=MagicMock(),
        )

        manager.setup()
        setup_jira_oauth_routes(app)

        assert self._count_callback_routes(app) == 1

    def test_setup_rejects_conflicting_existing_manager(self) -> None:
        app = web.Application()
        app["jira_oauth_manager"] = object()
        manager = JiraOAuthManager(
            client_id="x",
            client_secret="y",
            redirect_uri="https://h/cb",
            app=app,
            redis_client=MagicMock(),
        )

        with pytest.raises(RuntimeError, match="already set"):
            manager.setup()

    def test_setup_without_app_raises(self) -> None:
        manager = JiraOAuthManager(
            client_id="x",
            client_secret="y",
            redirect_uri="https://h/cb",
            redis_client=MagicMock(),
        )

        with pytest.raises(RuntimeError, match="app="):
            manager.setup()
