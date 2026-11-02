"""End-to-end integration tests for Jira OAuth callback routing (FEAT-225 / TASK-1474).

Covers the Slack bot wiring of the Jira OAuth manager. The legacy ``jira_oauth_callback`` channel
dispatch was removed in FEAT-773 (AC-14); callback behaviour is covered by
``tests/unit/test_oauth_callback_routes.py`` and ``tests/unit/integrations/oauth2/test_callback_web.py``.
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
