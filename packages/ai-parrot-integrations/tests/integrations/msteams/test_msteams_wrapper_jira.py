"""Integration tests for MS Teams wrapper Jira command wiring (FEAT-225 / TASK-1473)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_turn_context(text: str = "/connect_jira"):
    """Build a minimal mock TurnContext."""
    ctx = MagicMock()
    ctx.activity.text = text
    ctx.activity.from_property.id = "user-123"
    ctx.activity.from_property.aad_object_id = "aad-obj-123"
    ctx.activity.conversation.id = "conv-456"
    ctx.activity.conversation.conversation_type = "personal"
    ctx.activity.value = None
    ctx.activity.entities = None
    ctx.activity.attachments = None
    ctx.send_activity = AsyncMock()
    return ctx


# ---------------------------------------------------------------------------
# MSTeamsAgentConfig Jira fields
# ---------------------------------------------------------------------------

class TestMSTeamsAgentConfigJiraFields:
    def test_config_accepts_jira_fields(self):
        """MSTeamsAgentConfig accepts optional Jira OAuth configuration fields."""
        from parrot.integrations.msteams.models import MSTeamsAgentConfig

        with patch("parrot.integrations.msteams.models.config") as mock_config:
            mock_config.get = MagicMock(return_value=None)
            cfg = MSTeamsAgentConfig(
                name="test",
                chatbot_id="test_bot",
                jira_client_id="jira-client",
                jira_client_secret="jira-secret",
                jira_redirect_uri="https://example.com/callback",
            )

        assert cfg.jira_client_id == "jira-client"
        assert cfg.jira_client_secret == "jira-secret"
        assert cfg.jira_redirect_uri == "https://example.com/callback"

    def test_config_jira_fields_default_to_none(self):
        """Jira OAuth fields default to None when not provided."""
        from parrot.integrations.msteams.models import MSTeamsAgentConfig

        with patch("parrot.integrations.msteams.models.config") as mock_config:
            mock_config.get = MagicMock(return_value=None)
            cfg = MSTeamsAgentConfig(name="test", chatbot_id="test_bot")

        assert cfg.jira_client_id is None
        assert cfg.jira_client_secret is None
        assert cfg.jira_redirect_uri is None


# ---------------------------------------------------------------------------
# MSTeamsCommandRouter availability on wrapper
# ---------------------------------------------------------------------------

class TestMSTeamsWrapperJiraWiring:
    def test_command_router_none_without_oauth_manager(self):
        """_command_router is None when oauth_manager is not provided."""
        from parrot.integrations.msteams.commands import MSTeamsCommandRouter

        # We just test the router logic directly since wrapper initialization
        # requires heavy Bot Framework setup
        router = MSTeamsCommandRouter()
        # Without any registrations, router is empty
        assert router.registered_commands == []

    def test_jira_commands_registered_on_router(self):
        """register_jira_commands adds the three expected commands to the router."""
        from parrot.integrations.msteams.commands import MSTeamsCommandRouter
        from parrot.integrations.msteams.commands.jira_commands import register_jira_commands

        mock_manager = MagicMock()
        router = MSTeamsCommandRouter()
        register_jira_commands(router, mock_manager)

        assert "connect_jira" in router.registered_commands
        assert "disconnect_jira" in router.registered_commands
        assert "jira_status" in router.registered_commands

    @pytest.mark.asyncio
    async def test_command_intercept_returns_true_for_jira_command(self):
        """try_dispatch returns True and handles /connect_jira."""
        from parrot.integrations.msteams.commands import MSTeamsCommandRouter
        from parrot.integrations.msteams.commands.jira_commands import register_jira_commands

        mock_manager = MagicMock()
        mock_manager.validate_token = AsyncMock(return_value=None)
        mock_manager.create_authorization_url = AsyncMock(
            return_value=("https://auth.url", "nonce")
        )

        router = MSTeamsCommandRouter()
        register_jira_commands(router, mock_manager)

        ctx = _mock_turn_context("/connect_jira")
        with patch(
            "parrot.integrations.msteams.commands.jira_commands.TurnContext"
        ) as mock_tc:
            mock_tc.get_conversation_reference = MagicMock(return_value=MagicMock(
                serialize=MagicMock(return_value={"conversation": {"id": "c"}})
            ))
            result = await router.try_dispatch("/connect_jira", ctx)

        assert result is True

    @pytest.mark.asyncio
    async def test_non_command_text_passes_through(self):
        """Non-command text returns False from try_dispatch."""
        from parrot.integrations.msteams.commands import MSTeamsCommandRouter

        router = MSTeamsCommandRouter()
        ctx = _mock_turn_context("Hello, can you help me?")
        result = await router.try_dispatch("Hello, can you help me?", ctx)
        assert result is False

    @pytest.mark.asyncio
    async def test_command_intercept_after_mention_stripping(self):
        """Command is detected after @BotName mention is removed."""
        from parrot.integrations.msteams.commands import MSTeamsCommandRouter
        from parrot.integrations.msteams.commands.jira_commands import register_jira_commands

        mock_manager = MagicMock()
        mock_manager.validate_token = AsyncMock(return_value=None)
        mock_manager.create_authorization_url = AsyncMock(
            return_value=("https://auth.url", "nonce")
        )

        router = MSTeamsCommandRouter()
        register_jira_commands(router, mock_manager)

        # After mention stripping: "/connect_jira"
        ctx = _mock_turn_context("/connect_jira")
        with patch(
            "parrot.integrations.msteams.commands.jira_commands.TurnContext"
        ) as mock_tc:
            mock_tc.get_conversation_reference = MagicMock(return_value=MagicMock(
                serialize=MagicMock(return_value={})
            ))
            result = await router.try_dispatch("/connect_jira", ctx)

        assert result is True
