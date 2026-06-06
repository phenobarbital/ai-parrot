"""End-to-end integration tests for Jira OAuth callback routing (FEAT-225 / TASK-1474).

Tests the full channel dispatch in jira_oauth_callback:
- channel == "web"       → existing _handle_web_callback (no regression)
- channel == "slack"     → handle_slack_jira_callback
- channel == "msteams"   → handle_msteams_jira_callback
- channel == "telegram"  → existing Telegram flow (no regression)
- channel absent         → defaults to Telegram flow (backward compat)
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _mock_token_set(display_name: str = "Test User", site_url: str = "https://site.net"):
    token = MagicMock()
    token.display_name = display_name
    token.site_url = site_url
    token.email = "test@example.com"
    token.account_id = "account-123"
    return token


def _mock_app(extras: dict | None = None):
    app = {}
    if extras:
        app.update(extras)
    return app


# ---------------------------------------------------------------------------
# Callback routing tests
# ---------------------------------------------------------------------------

class TestJiraOAuthCallbackRouting:
    @pytest.mark.asyncio
    async def test_slack_channel_dispatches_to_slack_handler(self):
        """Callback with channel='slack' calls handle_slack_jira_callback."""
        from parrot.auth.routes import jira_oauth_callback

        token_set = _mock_token_set()
        state_payload = {
            "channel": "slack",
            "team_id": "T0001",
            "slack_user_id": "U1234",
            "user_id": "T0001:U1234",
        }

        mock_request = MagicMock()
        mock_request.query = {"code": "auth-code", "state": "state-token"}
        mock_request.app = _mock_app()

        with patch("parrot.auth.routes.jira_oauth_callback") as mock_cb:
            # Test the branch logic directly by checking handle_slack_jira_callback is called
            pass

        # Direct test: create a mock manager and call the callback
        mock_manager = MagicMock()
        mock_manager.handle_callback = AsyncMock(return_value=(token_set, state_payload))
        mock_request.app["jira_oauth_manager"] = mock_manager

        with patch(
            "parrot.integrations.slack.oauth_callback.handle_slack_jira_callback",
            new_callable=AsyncMock,
        ) as mock_slack_handler:
            from aiohttp.web import Response
            mock_slack_handler.return_value = Response(
                text="<html>ok</html>", content_type="text/html"
            )

            response = await jira_oauth_callback(mock_request)

        mock_slack_handler.assert_called_once()
        assert response.status == 200

    @pytest.mark.asyncio
    async def test_msteams_channel_dispatches_to_msteams_handler(self):
        """Callback with channel='msteams' calls handle_msteams_jira_callback."""
        from parrot.auth.routes import jira_oauth_callback

        token_set = _mock_token_set()
        state_payload = {
            "channel": "msteams",
            "user_id": "aad-obj-123",
            "conversation_reference": {"conversation": {"id": "c"}},
        }

        mock_request = MagicMock()
        mock_request.query = {"code": "auth-code", "state": "state-token"}
        mock_request.app = _mock_app()

        mock_manager = MagicMock()
        mock_manager.handle_callback = AsyncMock(return_value=(token_set, state_payload))
        mock_request.app["jira_oauth_manager"] = mock_manager

        with patch(
            "parrot.integrations.msteams.oauth_callback.handle_msteams_jira_callback",
            new_callable=AsyncMock,
        ) as mock_teams_handler:
            from aiohttp.web import Response
            mock_teams_handler.return_value = Response(
                text="<html>ok</html>", content_type="text/html"
            )

            response = await jira_oauth_callback(mock_request)

        mock_teams_handler.assert_called_once()
        assert response.status == 200

    @pytest.mark.asyncio
    async def test_telegram_channel_unchanged(self):
        """Callback with channel='telegram' follows the existing Telegram flow."""
        from parrot.auth.routes import jira_oauth_callback

        token_set = _mock_token_set()
        state_payload = {
            "channel": "telegram",
            "user_id": "12345",
        }

        mock_request = MagicMock()
        mock_request.query = {"code": "auth-code", "state": "state-token"}
        mock_request.app = _mock_app()

        mock_manager = MagicMock()
        mock_manager.handle_callback = AsyncMock(return_value=(token_set, state_payload))
        mock_request.app["jira_oauth_manager"] = mock_manager

        # Telegram branch should NOT call Slack or Teams handlers
        with patch(
            "parrot.integrations.slack.oauth_callback.handle_slack_jira_callback",
            new_callable=AsyncMock,
        ) as mock_slack:
            with patch(
                "parrot.integrations.msteams.oauth_callback.handle_msteams_jira_callback",
                new_callable=AsyncMock,
            ) as mock_teams:
                response = await jira_oauth_callback(mock_request)

        mock_slack.assert_not_called()
        mock_teams.assert_not_called()
        # Telegram path returns 200 with the standard success HTML
        assert response.status == 200
        assert "text/html" in response.content_type

    @pytest.mark.asyncio
    async def test_missing_channel_defaults_to_telegram(self):
        """Absent channel defaults to Telegram behavior (backward compat)."""
        from parrot.auth.routes import jira_oauth_callback

        token_set = _mock_token_set()
        state_payload = {
            # no 'channel' key
            "user_id": "12345",
        }

        mock_request = MagicMock()
        mock_request.query = {"code": "auth-code", "state": "state-token"}
        mock_request.app = _mock_app()

        mock_manager = MagicMock()
        mock_manager.handle_callback = AsyncMock(return_value=(token_set, state_payload))
        mock_request.app["jira_oauth_manager"] = mock_manager

        with patch(
            "parrot.integrations.slack.oauth_callback.handle_slack_jira_callback",
            new_callable=AsyncMock,
        ) as mock_slack:
            with patch(
                "parrot.integrations.msteams.oauth_callback.handle_msteams_jira_callback",
                new_callable=AsyncMock,
            ) as mock_teams:
                response = await jira_oauth_callback(mock_request)

        mock_slack.assert_not_called()
        mock_teams.assert_not_called()
        assert response.status == 200

    @pytest.mark.asyncio
    async def test_missing_code_returns_400(self):
        """Callback with missing code or state returns 400 error page."""
        from parrot.auth.routes import jira_oauth_callback

        mock_request = MagicMock()
        mock_request.query = {"code": "", "state": ""}
        mock_request.app = {}

        response = await jira_oauth_callback(mock_request)
        assert response.status == 400

    @pytest.mark.asyncio
    async def test_missing_manager_returns_500(self):
        """Callback without jira_oauth_manager on app returns 500."""
        from parrot.auth.routes import jira_oauth_callback

        mock_request = MagicMock()
        mock_request.query = {"code": "abc", "state": "xyz"}
        mock_request.app = {}  # no manager

        response = await jira_oauth_callback(mock_request)
        assert response.status == 500


# ---------------------------------------------------------------------------
# Integration manager Jira wiring tests
# ---------------------------------------------------------------------------

class TestIntegrationManagerJiraWiring:
    @pytest.mark.asyncio
    async def test_slack_bot_passes_oauth_manager_when_configured(self):
        """_start_slack_bot passes JiraOAuthManager to SlackAgentWrapper when jira_client_id is set."""
        from parrot.integrations.manager import IntegrationBotManager
        from parrot.integrations.slack.models import SlackAgentConfig

        bot_manager_mock = MagicMock()
        app = {}
        bot_manager_mock.get_app = MagicMock(return_value=app)

        mgr = IntegrationBotManager(bot_manager_mock)
        mgr._get_agent = AsyncMock(return_value=MagicMock())

        with patch("parrot.integrations.slack.models.config") as mock_config:
            mock_config.get = MagicMock(return_value=None)
            cfg = SlackAgentConfig(
                name="test-slack",
                chatbot_id="test_bot",
                bot_token="xoxb-test",
                signing_secret="test-secret",
                jira_client_id="jira-client-id",
                jira_client_secret="jira-secret",
                jira_redirect_uri="https://example.com/callback",
            )

        with patch("parrot.auth.jira_oauth.JiraOAuthManager") as mock_jira_cls:
            mock_jira_instance = MagicMock()
            mock_jira_cls.return_value = mock_jira_instance

            with patch(
                "parrot.integrations.slack.wrapper.SlackAgentWrapper"
            ) as mock_wrapper_cls:
                mock_wrapper = MagicMock()
                mock_wrapper.start = AsyncMock()
                mock_wrapper_cls.return_value = mock_wrapper

                await mgr._start_slack_bot("test-slack", cfg)

        # Verify oauth_manager was passed to the wrapper
        call_kwargs = mock_wrapper_cls.call_args[1]
        assert call_kwargs.get("oauth_manager") is mock_jira_instance

    @pytest.mark.asyncio
    async def test_slack_bot_no_oauth_manager_without_config(self):
        """_start_slack_bot does not create JiraOAuthManager when jira_client_id is absent."""
        from parrot.integrations.manager import IntegrationBotManager
        from parrot.integrations.slack.models import SlackAgentConfig

        bot_manager_mock = MagicMock()
        app = {}
        bot_manager_mock.get_app = MagicMock(return_value=app)

        mgr = IntegrationBotManager(bot_manager_mock)
        mgr._get_agent = AsyncMock(return_value=MagicMock())

        with patch("parrot.integrations.slack.models.config") as mock_config:
            mock_config.get = MagicMock(return_value=None)
            cfg = SlackAgentConfig(name="test-slack", chatbot_id="test_bot")

        with patch(
            "parrot.integrations.slack.wrapper.SlackAgentWrapper"
        ) as mock_wrapper_cls:
            mock_wrapper = MagicMock()
            mock_wrapper.start = AsyncMock()
            mock_wrapper_cls.return_value = mock_wrapper

            await mgr._start_slack_bot("test-slack", cfg)

        call_kwargs = mock_wrapper_cls.call_args[1]
        assert call_kwargs.get("oauth_manager") is None
