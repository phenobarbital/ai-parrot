"""Unit tests for the web-channel branch of jira_oauth_callback."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_token_set(
    account_id: str = "acct-1",
    display_name: str = "Test User",
    email: str = "test@example.com",
    site_url: str = "https://example.atlassian.net",
    cloud_id: str = "cloud-1",
    scopes: list | None = None,
) -> MagicMock:
    ts = MagicMock()
    ts.account_id = account_id
    ts.display_name = display_name
    ts.email = email
    ts.site_url = site_url
    ts.cloud_id = cloud_id
    ts.scopes = scopes or ["read:jira-work"]
    return ts


def _make_state_payload(
    channel: str = "web",
    user_id: str = "u1",
    return_origin: str = "https://app.example.com",
    agent_id: str = "agent1",
) -> dict:
    return {
        "channel": channel,
        "user_id": user_id,
        "extra": {
            "channel": channel,
            "return_origin": return_origin,
            "agent_id": agent_id,
        },
    }


def _make_request_with_app(
    code: str = "c",
    state: str = "s",
    app_data: dict | None = None,
) -> MagicMock:
    """Build a mocked aiohttp request whose app supports dict-style .get()."""
    from aiohttp.test_utils import make_mocked_request

    request = make_mocked_request(
        "GET",
        f"/api/auth/jira/callback?code={code}&state={state}",
    )

    data = dict(app_data or {})
    request.app.get.side_effect = lambda key, default=None: data.get(key, default)
    request.app.__getitem__ = MagicMock(side_effect=lambda key: data[key])
    return request


# ---------------------------------------------------------------------------
# TestWebCallbackBranch
# ---------------------------------------------------------------------------


class TestWebCallbackBranch:
    """Tests for the channel=="web" branch in jira_oauth_callback."""

    @pytest.mark.asyncio
    async def test_web_branch_renders_postmessage_html(self) -> None:
        """When channel=="web", response is HTML containing the postMessage script."""
        token_set = _make_token_set()
        state_payload = _make_state_payload()
        mock_manager = MagicMock(
            handle_callback=AsyncMock(return_value=(token_set, state_payload))
        )
        request = _make_request_with_app(
            app_data={
                "jira_oauth_manager": mock_manager,
                "jira_oauth_notifier": None,
            }
        )

        with patch(
            "parrot.auth.routes.WEB_OAUTH_ALLOWED_ORIGINS",
            ["https://app.example.com"],
        ), patch(
            "parrot.auth.routes.IntegrationsService"
        ) as MockSvc:
            MockSvc.return_value.persist_credential = AsyncMock()

            from parrot.auth.routes import jira_oauth_callback

            resp = await jira_oauth_callback(request)

        assert resp.content_type == "text/html"
        body = resp.text
        assert "ai-parrot-oauth-callback" in body
        assert "postMessage" in body
        assert "success: true" in body

    @pytest.mark.asyncio
    async def test_web_branch_calls_persist_credential(self) -> None:
        """persist_credential is called with user_id, provider, token_set."""
        token_set = _make_token_set()
        state_payload = _make_state_payload()
        mock_manager = MagicMock(
            handle_callback=AsyncMock(return_value=(token_set, state_payload))
        )
        request = _make_request_with_app(
            app_data={
                "jira_oauth_manager": mock_manager,
                "jira_oauth_notifier": None,
            }
        )

        persist_mock = AsyncMock()
        with patch(
            "parrot.auth.routes.WEB_OAUTH_ALLOWED_ORIGINS",
            ["https://app.example.com"],
        ), patch(
            "parrot.auth.routes.IntegrationsService"
        ) as MockSvc:
            MockSvc.return_value.persist_credential = persist_mock

            from parrot.auth.routes import jira_oauth_callback

            await jira_oauth_callback(request)

        persist_mock.assert_called_once_with("u1", "jira", token_set)

    @pytest.mark.asyncio
    async def test_invalid_return_origin_renders_error_template(self) -> None:
        """return_origin not in WEB_OAUTH_ALLOWED_ORIGINS → error HTML, status 400."""
        token_set = _make_token_set()
        state_payload = _make_state_payload(return_origin="https://evil.com")
        mock_manager = MagicMock(
            handle_callback=AsyncMock(return_value=(token_set, state_payload))
        )
        request = _make_request_with_app(
            app_data={
                "jira_oauth_manager": mock_manager,
                "jira_oauth_notifier": None,
            }
        )

        with patch(
            "parrot.auth.routes.WEB_OAUTH_ALLOWED_ORIGINS",
            ["https://app.example.com"],
        ), patch("parrot.auth.routes.IntegrationsService"):
            from parrot.auth.routes import jira_oauth_callback

            resp = await jira_oauth_callback(request)

        assert resp.status == 400
        assert "invalid_origin" in resp.text
        assert "success: false" in resp.text

    @pytest.mark.asyncio
    async def test_telegram_branch_unchanged(self) -> None:
        """Telegram-channel callback does NOT call persist_credential (regression guard)."""
        token_set = _make_token_set()
        state_payload = _make_state_payload(channel="telegram")
        state_payload["extra"] = {"chat_id": 12345}

        mock_manager = MagicMock(
            handle_callback=AsyncMock(return_value=(token_set, state_payload))
        )
        request = _make_request_with_app(
            app_data={
                "jira_oauth_manager": mock_manager,
                "jira_oauth_notifier": None,
                "telegram_jira_session_stamper": None,
            }
        )

        persist_mock = AsyncMock()
        with patch(
            "parrot.auth.routes.WEB_OAUTH_ALLOWED_ORIGINS",
            ["https://app.example.com"],
        ), patch(
            "parrot.auth.routes.IntegrationsService"
        ) as MockSvc:
            MockSvc.return_value.persist_credential = persist_mock

            from parrot.auth.routes import jira_oauth_callback

            resp = await jira_oauth_callback(request)

        # Telegram path renders the existing non-postMessage success page
        persist_mock.assert_not_called()
        assert resp.status == 200
        assert resp.content_type == "text/html"
        # Telegram success page has no postMessage
        assert "postMessage" not in resp.text

    @pytest.mark.asyncio
    async def test_missing_channel_defaults_to_telegram(self) -> None:
        """When state_payload has no 'channel' key, the Telegram flow runs (no persist)."""
        token_set = _make_token_set()
        # Old-style state_payload with no 'channel' key
        state_payload: dict = {
            "user_id": "u1",
            "extra": {"chat_id": 999},
        }

        mock_manager = MagicMock(
            handle_callback=AsyncMock(return_value=(token_set, state_payload))
        )
        request = _make_request_with_app(
            app_data={
                "jira_oauth_manager": mock_manager,
                "jira_oauth_notifier": None,
                "telegram_jira_session_stamper": None,
            }
        )

        persist_mock = AsyncMock()
        with patch(
            "parrot.auth.routes.WEB_OAUTH_ALLOWED_ORIGINS",
            ["https://app.example.com"],
        ), patch(
            "parrot.auth.routes.IntegrationsService"
        ) as MockSvc:
            MockSvc.return_value.persist_credential = persist_mock

            from parrot.auth.routes import jira_oauth_callback

            resp = await jira_oauth_callback(request)

        # No persist_credential for legacy/telegram-style callbacks
        persist_mock.assert_not_called()
        assert resp.status == 200
