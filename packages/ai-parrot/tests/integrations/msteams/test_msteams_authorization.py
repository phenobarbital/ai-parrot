"""Tests for MSTeamsAgentWrapper authorization logic (FEAT-037)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.integrations.msteams.models import MSTeamsAgentConfig
from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper
from botbuilder.schema import (
    Activity,
    ActivityTypes,
    ConversationAccount,
    ChannelAccount,
)


@pytest.fixture
def mock_agent():
    """Create a mock agent."""
    agent = MagicMock()
    agent.ask = AsyncMock()
    agent.tool_manager = MagicMock()
    agent.tool_manager.list_tools.return_value = []
    agent.register_tool = MagicMock()
    return agent


@pytest.fixture
def mock_app():
    """Create a mock aiohttp app."""
    app = MagicMock()
    app.router = MagicMock()
    app.get.return_value = None
    return app


def _make_config(**kwargs) -> MSTeamsAgentConfig:
    """Create a config with defaults and overrides."""
    defaults = {
        "name": "test_bot",
        "chatbot_id": "test_bot_id",
        "client_id": "fake_id",
        "client_secret": "fake_secret",
    }
    defaults.update(kwargs)
    return MSTeamsAgentConfig(**defaults)


@pytest.fixture
async def wrapper(mock_agent, mock_app):
    """Create a wrapper with mocked dependencies (needs event loop)."""
    config = _make_config()
    w = MSTeamsAgentWrapper(mock_agent, config, mock_app)
    w.form_orchestrator = AsyncMock()
    return w


class TestIsAuthorized:
    """Tests for _is_authorized() method.

    These tests construct the wrapper inside an async context to avoid
    the 'no running event loop' error from MSTeamsAgentWrapper.__init__.
    """

    @pytest.mark.asyncio
    async def test_authorized_when_no_whitelist(self, mock_agent, mock_app):
        """None whitelists allow all conversations and users."""
        config = _make_config()
        wrapper = MSTeamsAgentWrapper(mock_agent, config, mock_app)

        assert wrapper._is_authorized("any-conv", "any-user") is True

    @pytest.mark.asyncio
    async def test_authorized_conversation_in_list(self, mock_agent, mock_app):
        """Conversation in whitelist passes."""
        config = _make_config(
            allowed_conversation_ids=["19:abc@thread", "19:def@thread"]
        )
        wrapper = MSTeamsAgentWrapper(mock_agent, config, mock_app)

        assert wrapper._is_authorized("19:abc@thread", "any-user") is True

    @pytest.mark.asyncio
    async def test_unauthorized_conversation_not_in_list(self, mock_agent, mock_app):
        """Conversation not in whitelist is blocked."""
        config = _make_config(
            allowed_conversation_ids=["19:abc@thread"]
        )
        wrapper = MSTeamsAgentWrapper(mock_agent, config, mock_app)

        assert wrapper._is_authorized("19:other@thread", "any-user") is False

    @pytest.mark.asyncio
    async def test_authorized_user_in_list(self, mock_agent, mock_app):
        """User in whitelist passes."""
        config = _make_config(
            allowed_user_ids=["29:user1", "29:user2"]
        )
        wrapper = MSTeamsAgentWrapper(mock_agent, config, mock_app)

        assert wrapper._is_authorized("any-conv", "29:user1") is True

    @pytest.mark.asyncio
    async def test_unauthorized_user_not_in_list(self, mock_agent, mock_app):
        """User not in whitelist is blocked."""
        config = _make_config(
            allowed_user_ids=["29:user1"]
        )
        wrapper = MSTeamsAgentWrapper(mock_agent, config, mock_app)

        assert wrapper._is_authorized("any-conv", "29:other") is False

    @pytest.mark.asyncio
    async def test_both_filters_must_pass(self, mock_agent, mock_app):
        """Both conversation and user must be in their respective whitelists."""
        config = _make_config(
            allowed_conversation_ids=["19:abc@thread"],
            allowed_user_ids=["29:user1"],
        )
        wrapper = MSTeamsAgentWrapper(mock_agent, config, mock_app)

        # Both OK
        assert wrapper._is_authorized("19:abc@thread", "29:user1") is True
        # Conversation OK, user blocked
        assert wrapper._is_authorized("19:abc@thread", "29:other") is False
        # User OK, conversation blocked
        assert wrapper._is_authorized("19:other@thread", "29:user1") is False
        # Both blocked
        assert wrapper._is_authorized("19:other@thread", "29:other") is False


class TestOnMessageUnauthorized:
    """Tests for authorization check in on_message_activity."""

    @pytest.mark.asyncio
    async def test_on_message_unauthorized_sends_denial(self, mock_agent, mock_app):
        """Unauthorized user receives denial message."""
        config = _make_config(allowed_user_ids=["29:allowed-user"])
        wrapper = MSTeamsAgentWrapper(mock_agent, config, mock_app)
        wrapper.form_orchestrator = AsyncMock()

        # Create mock turn context
        turn_context = MagicMock()
        turn_context.activity = Activity(
            type=ActivityTypes.message,
            text="hello",
            conversation=ConversationAccount(id="19:conv@thread"),
            from_property=ChannelAccount(id="29:blocked-user"),
        )
        turn_context.send_activity = AsyncMock()

        await wrapper.on_message_activity(turn_context)

        # Should send denial message
        turn_context.send_activity.assert_called_once()
        denial_text = turn_context.send_activity.call_args[0][0]
        assert "not authorized" in denial_text.lower()
