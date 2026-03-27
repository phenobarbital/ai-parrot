"""Integration tests for MS Teams whitelist full flow (TASK-254).

Tests the full message processing flow through on_message_activity
with various whitelist configurations.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.integrations.msteams.models import MSTeamsAgentConfig
from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper
from botbuilder.schema import (
    Activity,
    ActivityTypes,
    ConversationAccount,
    ChannelAccount,
)


def _make_config(**kwargs) -> MSTeamsAgentConfig:
    """Create a MSTeamsAgentConfig with defaults and overrides."""
    defaults = {
        "name": "test_bot",
        "chatbot_id": "test_bot_id",
        "client_id": "fake_id",
        "client_secret": "fake_secret",
    }
    defaults.update(kwargs)
    return MSTeamsAgentConfig(**defaults)


def _make_turn_context(
    conversation_id: str,
    user_id: str,
    text: str = "hello",
    channel_id: str = "msteams",
):
    """Create a mock TurnContext with a fully populated activity."""
    turn_context = MagicMock()
    turn_context.activity = Activity(
        type=ActivityTypes.message,
        text=text,
        channel_id=channel_id,
        conversation=ConversationAccount(id=conversation_id),
        from_property=ChannelAccount(id=user_id, name="Test User"),
        service_url="https://smba.trafficmanager.net/teams/",
    )
    turn_context.send_activity = AsyncMock()
    return turn_context


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


class TestMSTeamsWhitelistIntegration:
    """Full-flow integration tests for MS Teams whitelist authorization."""

    @pytest.mark.asyncio
    async def test_message_blocked_by_conversation_whitelist(
        self, mock_agent, mock_app
    ):
        """Message from non-whitelisted conversation gets denial response."""
        config = _make_config(
            allowed_conversation_ids=["19:allowed@thread.tacv2"]
        )
        wrapper = MSTeamsAgentWrapper(mock_agent, config, mock_app)
        wrapper.form_orchestrator = AsyncMock()

        turn_context = _make_turn_context(
            conversation_id="19:blocked@thread.tacv2",
            user_id="29:some-user",
            text="What is the status?",
        )

        await wrapper.on_message_activity(turn_context)

        # Should send denial and NOT process the message
        turn_context.send_activity.assert_called_once()
        denial_text = turn_context.send_activity.call_args[0][0]
        assert "not authorized" in denial_text.lower()
        mock_agent.ask.assert_not_called()

    @pytest.mark.asyncio
    async def test_message_blocked_by_user_whitelist(
        self, mock_agent, mock_app
    ):
        """Message from non-whitelisted user gets denial response."""
        config = _make_config(
            allowed_user_ids=["29:allowed-user"]
        )
        wrapper = MSTeamsAgentWrapper(mock_agent, config, mock_app)
        wrapper.form_orchestrator = AsyncMock()

        turn_context = _make_turn_context(
            conversation_id="19:any-conv@thread",
            user_id="29:blocked-user",
            text="Show me the report",
        )

        await wrapper.on_message_activity(turn_context)

        turn_context.send_activity.assert_called_once()
        denial_text = turn_context.send_activity.call_args[0][0]
        assert "not authorized" in denial_text.lower()
        mock_agent.ask.assert_not_called()

    @pytest.mark.asyncio
    async def test_message_allowed_by_whitelist(
        self, mock_agent, mock_app
    ):
        """Message from whitelisted conversation + user passes authorization."""
        config = _make_config(
            allowed_conversation_ids=["19:allowed@thread.tacv2"],
            allowed_user_ids=["29:allowed-user"],
        )
        wrapper = MSTeamsAgentWrapper(mock_agent, config, mock_app)
        wrapper.form_orchestrator = AsyncMock()

        turn_context = _make_turn_context(
            conversation_id="19:allowed@thread.tacv2",
            user_id="29:allowed-user",
            text="Process this",
        )

        # Authorization should pass — mock everything after the auth check
        # to avoid needing full bot framework setup
        with patch.object(wrapper, "dialogs", create=True) as mock_dialogs:
            mock_dc = AsyncMock()
            mock_dc.continue_dialog = AsyncMock(return_value=MagicMock(status="empty"))
            mock_dialogs.create_context = AsyncMock(return_value=mock_dc)
            wrapper._process_text_message = AsyncMock()
            wrapper.form_orchestrator.check_for_form_trigger = AsyncMock(
                return_value=None
            )

            await wrapper.on_message_activity(turn_context)

        # Should NOT send denial
        denial_calls = [
            call for call in turn_context.send_activity.call_args_list
            if call[0] and "not authorized" in str(call[0][0]).lower()
        ]
        assert len(denial_calls) == 0

    @pytest.mark.asyncio
    async def test_no_whitelist_allows_all(
        self, mock_agent, mock_app
    ):
        """No whitelist config allows all messages through."""
        config = _make_config()
        wrapper = MSTeamsAgentWrapper(mock_agent, config, mock_app)
        wrapper.form_orchestrator = AsyncMock()

        turn_context = _make_turn_context(
            conversation_id="19:any-conv@thread",
            user_id="29:any-user",
            text="Hello bot",
        )

        with patch.object(wrapper, "dialogs", create=True) as mock_dialogs:
            mock_dc = AsyncMock()
            mock_dc.continue_dialog = AsyncMock(return_value=MagicMock(status="empty"))
            mock_dialogs.create_context = AsyncMock(return_value=mock_dc)
            wrapper._process_text_message = AsyncMock()
            wrapper.form_orchestrator.check_for_form_trigger = AsyncMock(
                return_value=None
            )

            await wrapper.on_message_activity(turn_context)

        # Should NOT send denial
        denial_calls = [
            call for call in turn_context.send_activity.call_args_list
            if call[0] and "not authorized" in str(call[0][0]).lower()
        ]
        assert len(denial_calls) == 0
