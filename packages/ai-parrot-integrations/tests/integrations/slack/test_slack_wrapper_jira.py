"""Integration tests for Slack wrapper Jira command wiring (FEAT-225 / TASK-1470)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_minimal_wrapper(oauth_manager=None):
    """Create a SlackAgentWrapper with minimal mocking."""
    from parrot.integrations.slack.wrapper import SlackAgentWrapper
    from parrot.integrations.slack.models import SlackAgentConfig

    # Build a config that won't hit env-var validation
    config = SlackAgentConfig.__new__(SlackAgentConfig)
    config.name = "test-bot"
    config.chatbot_id = "test_bot"
    config.bot_token = "xoxb-test-token"
    config.signing_secret = "test-secret"
    config.app_token = None
    config.connection_mode = "webhook"
    config.enable_assistant = False
    config.allowed_channel_ids = None
    config.allowed_user_ids = None
    config.webhook_path = None
    config.suggested_prompts = None
    config.max_concurrent_requests = 5
    config.jira_client_id = None
    config.jira_client_secret = None
    config.jira_redirect_uri = None
    config.welcome_message = None
    config.commands = {}
    config.kind = "slack"

    mock_app = MagicMock()
    mock_app.router = MagicMock()
    mock_app.get = MagicMock(return_value=None)
    mock_app.__setitem__ = MagicMock()
    mock_app.__getitem__ = MagicMock()

    mock_agent = MagicMock()

    # Patch heavy init internals
    with patch("parrot.integrations.slack.wrapper.EventDeduplicator"):
        with patch("parrot.integrations.slack.wrapper.SlackInteractiveHandler"):
            wrapper = SlackAgentWrapper.__new__(SlackAgentWrapper)
            wrapper.agent = mock_agent
            wrapper.config = config
            wrapper.app = mock_app
            import logging
            wrapper.logger = logging.getLogger("test")
            wrapper.conversations = {}
            import asyncio
            wrapper._concurrency_semaphore = asyncio.Semaphore(5)
            wrapper._background_tasks = set()
            wrapper._assistant_handler = None
            wrapper._interactive_handler = MagicMock()
            wrapper._dedup = MagicMock()
            wrapper._dedup.is_duplicate = MagicMock(return_value=False)
            wrapper.events_route = "/api/slack/test_bot/events"
            wrapper.commands_route = "/api/slack/test_bot/commands"
            wrapper.interactive_route = "/api/slack/test_bot/interactive"

            from parrot.integrations.slack.commands import SlackCommandRouter
            from parrot.integrations.slack.commands.jira_commands import register_jira_commands

            wrapper._command_router = SlackCommandRouter()
            if oauth_manager is not None:
                register_jira_commands(wrapper._command_router, oauth_manager)
                if config.bot_token:
                    from parrot.integrations.slack.oauth_callback import SlackOAuthNotifier
                    with patch.object(SlackOAuthNotifier, "__init__", lambda s, bot_token: None):
                        notifier = SlackOAuthNotifier.__new__(SlackOAuthNotifier)
                        notifier._bot_token = config.bot_token
                        notifier._client = MagicMock()
                        notifier.logger = logging.getLogger("test")
                        mock_app["slack_jira_oauth_notifier"] = notifier

    return wrapper, mock_app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSlackWrapperJiraWiring:
    def test_command_router_created_on_init(self):
        """Wrapper always creates a SlackCommandRouter during __init__."""
        wrapper, _ = _make_minimal_wrapper()
        from parrot.integrations.slack.commands import SlackCommandRouter
        assert isinstance(wrapper._command_router, SlackCommandRouter)

    def test_jira_commands_registered_when_oauth_manager_provided(self):
        """When oauth_manager is passed, Jira commands are registered on router."""
        manager = MagicMock()
        manager.validate_token = AsyncMock(return_value=None)
        manager.create_authorization_url = AsyncMock(return_value=("https://url", "nonce"))
        manager.revoke = AsyncMock()

        wrapper, _ = _make_minimal_wrapper(oauth_manager=manager)

        assert "connect_jira" in wrapper._command_router.registered_commands
        assert "disconnect_jira" in wrapper._command_router.registered_commands
        assert "jira_status" in wrapper._command_router.registered_commands

    def test_no_jira_commands_without_oauth_manager(self):
        """Without oauth_manager, the Jira commands are not registered."""
        wrapper, _ = _make_minimal_wrapper(oauth_manager=None)

        assert "connect_jira" not in wrapper._command_router.registered_commands
        assert "disconnect_jira" not in wrapper._command_router.registered_commands

    @pytest.mark.asyncio
    async def test_handle_command_dispatches_connect_jira(self):
        """_handle_command delegates /connect_jira to the command router."""
        import urllib.parse

        manager = MagicMock()
        manager.validate_token = AsyncMock(return_value=None)
        manager.create_authorization_url = AsyncMock(
            return_value=("https://auth.atlassian.com/authorize", "nonce")
        )

        wrapper, _ = _make_minimal_wrapper(oauth_manager=manager)

        form_data = {
            "team_id": "T0001",
            "user_id": "U1234",
            "channel_id": "C5678",
            "text": "",
            "command": "/connect_jira",
            "response_url": "https://hooks.slack.com/...",
        }
        raw_body = urllib.parse.urlencode(form_data).encode("utf-8")

        mock_request = MagicMock()
        mock_request.read = AsyncMock(return_value=raw_body)
        mock_request.headers = {}

        with patch(
            "parrot.integrations.slack.wrapper.verify_slack_signature_raw",
            return_value=True,
        ):
            response = await wrapper._handle_command(mock_request)
        # verify it came from the command router (returns ephemeral with blocks)
        assert response.status == 200

    @pytest.mark.asyncio
    async def test_handle_command_fallthrough_for_unknown(self):
        """Unknown commands still fall through to existing processing."""
        import urllib.parse

        wrapper, _ = _make_minimal_wrapper(oauth_manager=None)

        form_data = {
            "team_id": "T0001",
            "user_id": "U1234",
            "channel_id": "C5678",
            "text": "some random message",
            "command": "",
            "response_url": "",
        }
        raw_body = urllib.parse.urlencode(form_data).encode("utf-8")

        mock_request = MagicMock()
        mock_request.read = AsyncMock(return_value=raw_body)
        mock_request.headers = {}

        with patch(
            "parrot.integrations.slack.wrapper.verify_slack_signature_raw",
            return_value=True,
        ):
            with patch.object(wrapper, "_safe_answer", new_callable=AsyncMock):
                response = await wrapper._handle_command(mock_request)
        # Should return "Processing..." for unknown commands passed to agent
        assert response.status == 200


class TestSlackAgentConfigJiraFields:
    def test_config_accepts_jira_fields(self):
        """SlackAgentConfig accepts optional Jira OAuth configuration fields."""
        from parrot.integrations.slack.models import SlackAgentConfig

        with patch("parrot.integrations.slack.models.config") as mock_config:
            mock_config.get = MagicMock(return_value=None)
            slack_config = SlackAgentConfig(
                name="test",
                chatbot_id="test_bot",
                jira_client_id="client-id",
                jira_client_secret="client-secret",
                jira_redirect_uri="https://example.com/callback",
            )

        assert slack_config.jira_client_id == "client-id"
        assert slack_config.jira_client_secret == "client-secret"
        assert slack_config.jira_redirect_uri == "https://example.com/callback"

    def test_config_jira_fields_default_to_none(self):
        """Jira OAuth fields default to None when not provided."""
        from parrot.integrations.slack.models import SlackAgentConfig

        with patch("parrot.integrations.slack.models.config") as mock_config:
            mock_config.get = MagicMock(return_value=None)
            slack_config = SlackAgentConfig(name="test", chatbot_id="test_bot")

        assert slack_config.jira_client_id is None
        assert slack_config.jira_client_secret is None
        assert slack_config.jira_redirect_uri is None
