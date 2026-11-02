"""Unit tests for the generic OAuth2 callback's web-channel branch."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp.test_utils import make_mocked_request

from parrot.auth.oauth2_routes import make_oauth2_callback


def _make_token_set() -> MagicMock:
    token_set = MagicMock()
    token_set.account_id = "acct-1"
    token_set.display_name = "Test User"
    return token_set


def _make_state_payload(return_origin: str = "https://app.example.com") -> dict:
    return {
        "channel": "web",
        "nav_user_id": "42",
        "canonical_identity": "test@example.com",
        "extra": {
            "provider_id": "jira",
            "return_origin": return_origin,
        },
    }


def _make_request(manager: MagicMock) -> MagicMock:
    request = make_mocked_request(
        "GET",
        "/api/auth/jira/callback?code=c&state=s",
    )
    request.app.get.side_effect = lambda key, default=None: {
        "oauth2_manager_jira": manager,
    }.get(key, default)
    return request


class TestWebCallbackBranch:
    """Exercise web completion through ``make_oauth2_callback``."""

    @pytest.mark.asyncio
    async def test_web_branch_renders_postmessage_html(self) -> None:
        token_set = _make_token_set()
        manager = MagicMock()
        manager.handle_callback = AsyncMock(return_value=(token_set, _make_state_payload()))
        request = _make_request(manager)

        with (
            patch(
                "parrot.auth.oauth2_routes.WEB_OAUTH_ALLOWED_ORIGINS",
                ["https://app.example.com"],
            ),
            patch("parrot.auth.oauth2_routes.IntegrationsService") as service,
        ):
            service.return_value.persist_credential = AsyncMock()
            response = await make_oauth2_callback("jira")(request)

        assert response.content_type == "text/html"
        assert "ai-parrot-oauth-callback" in response.text
        assert "postMessage" in response.text
        assert "success: true" in response.text

    @pytest.mark.asyncio
    async def test_web_branch_calls_persist_credential(self) -> None:
        token_set = _make_token_set()
        manager = MagicMock()
        manager.handle_callback = AsyncMock(return_value=(token_set, _make_state_payload()))
        request = _make_request(manager)
        persist_credential = AsyncMock()

        with (
            patch(
                "parrot.auth.oauth2_routes.WEB_OAUTH_ALLOWED_ORIGINS",
                ["https://app.example.com"],
            ),
            patch("parrot.auth.oauth2_routes.IntegrationsService") as service,
        ):
            service.return_value.persist_credential = persist_credential
            await make_oauth2_callback("jira")(request)

        persist_credential.assert_awaited_once_with(
            "42",
            "jira",
            token_set,
            channel="web",
            canonical_identity="test@example.com",
        )

    @pytest.mark.asyncio
    async def test_invalid_return_origin_renders_error_template(self) -> None:
        manager = MagicMock()
        manager.handle_callback = AsyncMock(return_value=(_make_token_set(), _make_state_payload("https://evil.com")))
        request = _make_request(manager)

        with (
            patch(
                "parrot.auth.oauth2_routes.WEB_OAUTH_ALLOWED_ORIGINS",
                ["https://app.example.com"],
            ),
            patch("parrot.auth.oauth2_routes.IntegrationsService") as service,
        ):
            response = await make_oauth2_callback("jira")(request)

        assert response.status == 400
        assert "invalid_origin" in response.text
        assert "success: false" in response.text
        service.assert_not_called()
