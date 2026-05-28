
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper
from parrot.integrations.msteams.models import MSTeamsAgentConfig
from botbuilder.core import TurnContext
from botbuilder.schema import Activity, ActivityTypes, ConversationAccount, ChannelAccount, Entity
from botbuilder.dialogs import DialogTurnStatus

@pytest.fixture
def mock_config():
    return MSTeamsAgentConfig(
        name="test_bot",
        chatbot_id="test_bot_id",
        client_id="fake_id",
        client_secret="fake_secret",
        enable_group_mentions=True
    )

@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.ask = AsyncMock()
    # Mock ask to return a simple response
    response_mock = MagicMock()
    response_mock.output = "Hello!"
    agent.ask.return_value = response_mock
    
    # Mock tool manager
    agent.tool_manager = MagicMock()
    agent.tool_manager.list_tools.return_value = []
    
    # Mock register_tool as sync
    agent.register_tool = MagicMock()
    
    return agent

@pytest.fixture
def mock_app():
    app = MagicMock()
    app.router = MagicMock()
    app.get.return_value = None  # No auth middleware for test
    return app

@pytest.fixture
async def wrapper(mock_agent, mock_config, mock_app):
    wrapper = MSTeamsAgentWrapper(mock_agent, mock_config, mock_app)
    # Mock internal components to avoid complex setup
    wrapper.form_orchestrator = AsyncMock()
    wrapper.form_orchestrator.process_message.return_value = MagicMock(needs_form=False, has_error=False, raw_response="Response")
    wrapper.send_typing = AsyncMock()
    wrapper._send_parsed_response = AsyncMock()
    wrapper._remove_mentions = MagicMock(side_effect=lambda act, txt: txt.replace("@BotName", "").strip())
    return wrapper

@pytest.mark.asyncio
async def test_channel_message_with_mention(wrapper):
    """Test standard channel message where bot is mentioned."""
    # Setup context
    turn_context = MagicMock(spec=TurnContext)
    
    mention_entity = Entity(type="mention")
    mention_entity.additional_properties = {"mentioned": {"id": "bot_id"}}
    
    activity = Activity(
        type=ActivityTypes.message,
        text="@BotName Hello",
        conversation=ConversationAccount(conversation_type="channel"),
        recipient=ChannelAccount(id="bot_id", name="BotName"),
        entities=[mention_entity],
        from_property=ChannelAccount(id="user_id")
    )
    turn_context.activity = activity
    
    # Mock dialog context
    wrapper.dialogs.create_context = AsyncMock()
    wrapper.dialogs.create_context.return_value.continue_dialog = AsyncMock()
    wrapper.dialogs.create_context.return_value.continue_dialog.return_value.status = DialogTurnStatus.Empty

    # Execute
    await wrapper.on_message_activity(turn_context)

    # Verify
    # Should force mention removal
    wrapper._remove_mentions.assert_called_once()
    # Should process message
    wrapper.form_orchestrator.process_message.assert_called_once()


@pytest.mark.asyncio
async def test_channel_message_no_mention(wrapper):
    """Test channel message where bot is NOT mentioned - should be ignored."""
    # Setup context
    turn_context = MagicMock(spec=TurnContext)
    activity = Activity(
        type=ActivityTypes.message,
        text="Hello everyone",
        conversation=ConversationAccount(conversation_type="channel"),
        recipient=ChannelAccount(id="bot_id", name="BotName"),
        entities=[], # No mentions
        from_property=ChannelAccount(id="user_id")
    )
    turn_context.activity = activity
    
    # Mock dialog context
    wrapper.dialogs.create_context = AsyncMock()
    wrapper.dialogs.create_context.return_value.continue_dialog = AsyncMock()
    wrapper.dialogs.create_context.return_value.continue_dialog.return_value.status = DialogTurnStatus.Empty

    # Execute
    await wrapper.on_message_activity(turn_context)

    # Verify
    # Should NOT process message
    wrapper.form_orchestrator.process_message.assert_not_called()


@pytest.mark.asyncio
async def test_personal_message_no_mention(wrapper):
    """Test personal chat message without mention - should be processed."""
    # Setup context
    turn_context = MagicMock(spec=TurnContext)
    activity = Activity(
        type=ActivityTypes.message,
        text="Hello",
        conversation=ConversationAccount(conversation_type="personal"),
        recipient=ChannelAccount(id="bot_id", name="BotName"),
        entities=[], 
        from_property=ChannelAccount(id="user_id")
    )
    turn_context.activity = activity
    
    # Mock dialog context
    wrapper.dialogs.create_context = AsyncMock()
    wrapper.dialogs.create_context.return_value.continue_dialog = AsyncMock()
    wrapper.dialogs.create_context.return_value.continue_dialog.return_value.status = DialogTurnStatus.Empty

    # Execute
    await wrapper.on_message_activity(turn_context)

    # Verify
    # Should process message even without mention
    wrapper.form_orchestrator.process_message.assert_called_once()

@pytest.mark.asyncio
async def test_channel_message_disabled_mentions(wrapper):
    """Test channel message when mentions are disabled."""
    wrapper.config.enable_group_mentions = False
    
    # Setup context
    turn_context = MagicMock(spec=TurnContext)
    
    mention_entity = Entity(type="mention")
    mention_entity.additional_properties = {"mentioned": {"id": "bot_id"}}

    activity = Activity(
        type=ActivityTypes.message,
        text="@BotName Hello",
        conversation=ConversationAccount(conversation_type="channel"),
        recipient=ChannelAccount(id="bot_id", name="BotName"),
        entities=[mention_entity],
        from_property=ChannelAccount(id="user_id")
    )
    turn_context.activity = activity
    
    # Mock dialog context
    wrapper.dialogs.create_context = AsyncMock()
    wrapper.dialogs.create_context.return_value.continue_dialog = AsyncMock()
    wrapper.dialogs.create_context.return_value.continue_dialog.return_value.status = DialogTurnStatus.Empty

    # Execute
    await wrapper.on_message_activity(turn_context)

    # Verify
    # Should NOT process message because config is disabled
    wrapper.form_orchestrator.process_message.assert_not_called()
