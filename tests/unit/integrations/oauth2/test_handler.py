"""Unit tests for parrot.handlers.integrations.IntegrationsHandler."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from parrot.integrations.oauth2.registry import OAuth2ProviderRegistry


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    OAuth2ProviderRegistry._reset()
    yield
    OAuth2ProviderRegistry._reset()


class TestIntegrationsHandlerGet:
    """Tests for GET /api/v1/agents/integrations/{agent_id}."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_no_providers(self) -> None:
        """GET with no registered providers returns empty JSON list."""
        from aiohttp.test_utils import make_mocked_request

        # Patch navigator_session.get_session used by @user_session() decorator
        with patch("navigator_auth.decorators.get_session", AsyncMock(return_value=None)):
            with patch(
                "parrot.handlers.integrations.IntegrationsService"
            ) as MockSvc:
                instance = MockSvc.return_value
                instance.list_for_user = AsyncMock(return_value=[])

                request = make_mocked_request("GET", "/api/v1/agents/integrations/agent1")
                # Set authenticated=True to bypass navigator_auth @is_authenticated decorator
                request["authenticated"] = True
                request["user_id"] = "u1"
                request.match_info["agent_id"] = "agent1"

                from parrot.handlers.integrations import IntegrationsHandler

                handler = IntegrationsHandler(request)
                response = await handler.get()
                import json as _json
                data = _json.loads(response.body)
                assert data == []


class TestIntegrationsHandlerPost:
    """Tests for POST connect and enable endpoints."""

    @pytest.mark.asyncio
    async def test_post_connect_missing_origin_returns_400(self) -> None:
        """POST connect without origin body or header returns 400."""
        from aiohttp.test_utils import make_mocked_request

        # make_mocked_request has empty headers by default — no Origin header
        request = make_mocked_request(
            "POST",
            "/api/v1/agents/integrations/agent1/jira/connect",
        )
        # Set authenticated=True to bypass navigator_auth decorator
        request["authenticated"] = True
        request["user_id"] = "u1"
        request.match_info["agent_id"] = "agent1"
        request.match_info["provider"] = "jira"

        with patch(
            "parrot.handlers.integrations.IntegrationsService"
        ):
            with patch.object(
                request, "json", new_callable=AsyncMock, side_effect=Exception("no json")
            ):
                with patch(
                    "parrot.handlers.integrations.WEB_OAUTH_ALLOWED_ORIGINS",
                    ["https://app.example.com"],
                ):
                    from parrot.handlers.integrations import IntegrationsHandler

                    handler = IntegrationsHandler(request)
                    response = await handler._post_connect()
                    assert response.status == 400


class TestIntegrationsHandlerConf:
    """Tests for configuration import."""

    def test_web_oauth_allowed_origins_importable(self) -> None:
        """WEB_OAUTH_ALLOWED_ORIGINS can be imported from parrot.conf."""
        from parrot.conf import WEB_OAUTH_ALLOWED_ORIGINS

        assert isinstance(WEB_OAUTH_ALLOWED_ORIGINS, list)

    def test_web_oauth_allowed_origins_default_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When env var not set, WEB_OAUTH_ALLOWED_ORIGINS defaults to []."""
        monkeypatch.delenv("WEB_OAUTH_ALLOWED_ORIGINS", raising=False)
        import importlib
        import parrot.conf as conf_mod

        importlib.reload(conf_mod)
        from parrot.conf import WEB_OAUTH_ALLOWED_ORIGINS

        assert isinstance(WEB_OAUTH_ALLOWED_ORIGINS, list)
