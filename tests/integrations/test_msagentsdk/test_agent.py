"""
Unit tests for ParrotM365Agent (bridge between SDK TurnContext and AbstractBot).

All tests mock the ``microsoft_agents.*`` SDK so the suite runs without the
optional dependency installed.
"""
import pytest
from unittest.mock import ANY, AsyncMock, MagicMock, patch


def _activity_module():
    """Mocked ``microsoft_agents.activity`` whose ``Activity`` records kwargs.

    Lets assertions inspect the ``text`` of the Activity the bridge sends,
    while keeping the suite runnable without the real SDK installed.
    """
    class _Activity:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    at = MagicMock()
    at.message = "message"
    at.conversation_update = "conversationUpdate"
    mod = MagicMock(
        Activity=_Activity,
        ActivityTypes=at,
        TextFormatTypes=MagicMock(plain="plain"),
    )
    return mod


def _sent_text(mock_context):
    """Return the ``text`` of the last Activity passed to ``send_activity``."""
    arg = mock_context.send_activity.call_args.args[0]
    return getattr(arg, "text", arg)


@pytest.fixture
def agent(mock_bot):
    """ParrotM365Agent wrapping the mock bot."""
    from parrot.integrations.msagentsdk.agent import ParrotM365Agent

    return ParrotM365Agent(mock_bot)


@pytest.fixture
def mock_context():
    """Mock TurnContext with a default message activity."""
    ctx = AsyncMock()
    ctx.activity = MagicMock()
    ctx.activity.type = "message"
    ctx.activity.text = "Hello, agent!"
    # Explicitly set aad_object_id/aadObjectId=None so the agent falls back to
    # the channel-level id ("user-123"). Without this, MagicMock auto-creates
    # truthy attributes and the agent uses those instead.
    from_prop = MagicMock(id="user-123")
    from_prop.aad_object_id = None
    from_prop.aadObjectId = None
    ctx.activity.from_property = from_prop
    ctx.activity.conversation = MagicMock(id="conv-456")
    ctx.activity.recipient = MagicMock(id="bot-789")
    ctx.activity.members_added = None
    ctx.send_activity = AsyncMock()
    return ctx


class TestParrotM365AgentInit:
    def test_default_welcome_message(self, mock_bot):
        """Default welcome message is used when none is provided."""
        from parrot.integrations.msagentsdk.agent import ParrotM365Agent

        a = ParrotM365Agent(mock_bot)
        assert a.welcome_message == "Hello! I'm ready to help."

    def test_custom_welcome_message(self, mock_bot):
        """Custom welcome message is stored correctly."""
        from parrot.integrations.msagentsdk.agent import ParrotM365Agent

        a = ParrotM365Agent(mock_bot, welcome_message="Howdy!")
        assert a.welcome_message == "Howdy!"


class TestParrotM365AgentOnTurn:
    @pytest.mark.asyncio
    async def test_message_calls_ask(self, agent, mock_context, mock_bot):
        """Message activity routes to ask() with correct args."""
        with patch(
            "parrot.integrations.msagentsdk.agent.ParrotM365Agent.on_turn",
            wraps=agent.on_turn,
        ):
            # Mock the lazy import of the activity module
            with patch.dict(
                "sys.modules",
                {"microsoft_agents.activity": _activity_module()},
            ):
                await agent.on_turn(mock_context)

        mock_bot.ask.assert_called_once_with(
            question="Hello, agent!",
            session_id="conv-456",
            user_id="user-123",
            ctx=ANY,
            # FEAT-264: the caller PermissionContext must reach ask() so the
            # broker seam can resolve per-user credentials (see _handle_message).
            permission_context=ANY,
        )
        mock_context.send_activity.assert_called_once()
        assert _sent_text(mock_context) == "Test response"

    @pytest.mark.asyncio
    async def test_empty_text_ignored(self, agent, mock_context, mock_bot):
        """Empty text does not call ask()."""
        mock_context.activity.text = ""
        mock_at = MagicMock()
        mock_at.message = "message"
        mock_at.conversation_update = "conversationUpdate"
        with patch.dict(
            "sys.modules",
            {"microsoft_agents.activity": MagicMock(ActivityTypes=mock_at)},
        ):
            await agent.on_turn(mock_context)
        mock_bot.ask.assert_not_called()

    @pytest.mark.asyncio
    async def test_none_text_ignored(self, agent, mock_context, mock_bot):
        """None text does not call ask()."""
        mock_context.activity.text = None
        mock_at = MagicMock()
        mock_at.message = "message"
        mock_at.conversation_update = "conversationUpdate"
        with patch.dict(
            "sys.modules",
            {"microsoft_agents.activity": MagicMock(ActivityTypes=mock_at)},
        ):
            await agent.on_turn(mock_context)
        mock_bot.ask.assert_not_called()

    @pytest.mark.asyncio
    async def test_whitespace_only_text_ignored(self, agent, mock_context, mock_bot):
        """Whitespace-only text does not call ask()."""
        mock_context.activity.text = "   "
        mock_at = MagicMock()
        mock_at.message = "message"
        mock_at.conversation_update = "conversationUpdate"
        with patch.dict(
            "sys.modules",
            {"microsoft_agents.activity": MagicMock(ActivityTypes=mock_at)},
        ):
            await agent.on_turn(mock_context)
        mock_bot.ask.assert_not_called()

    @pytest.mark.asyncio
    async def test_conversation_update_welcome(self, agent, mock_context):
        """conversationUpdate with new members triggers welcome message."""
        mock_context.activity.type = "conversationUpdate"
        new_member = MagicMock(id="new-user")
        mock_context.activity.members_added = [new_member]
        with patch.dict(
            "sys.modules",
            {"microsoft_agents.activity": _activity_module()},
        ):
            await agent.on_turn(mock_context)
        mock_context.send_activity.assert_called_once()
        assert _sent_text(mock_context) == agent.welcome_message

    @pytest.mark.asyncio
    async def test_bot_is_not_welcomed(self, agent, mock_context):
        """The bot itself is not sent the welcome message."""
        mock_context.activity.type = "conversationUpdate"
        # A member with same ID as recipient (the bot) plus a new human
        bot_member = MagicMock(id="bot-789")
        human_member = MagicMock(id="new-user")
        mock_context.activity.members_added = [bot_member, human_member]
        mock_at = MagicMock()
        mock_at.message = "message"
        mock_at.conversation_update = "conversationUpdate"
        with patch.dict(
            "sys.modules",
            {"microsoft_agents.activity": MagicMock(ActivityTypes=mock_at)},
        ):
            await agent.on_turn(mock_context)
        # Only the human member should receive the welcome message
        assert mock_context.send_activity.call_count == 1

    @pytest.mark.asyncio
    async def test_unknown_activity_type_ignored(self, agent, mock_context, mock_bot):
        """Unknown activity types do not call ask() or send_activity()."""
        mock_context.activity.type = "invoke"
        mock_at = MagicMock()
        mock_at.message = "message"
        mock_at.conversation_update = "conversationUpdate"
        with patch.dict(
            "sys.modules",
            {"microsoft_agents.activity": MagicMock(ActivityTypes=mock_at)},
        ):
            await agent.on_turn(mock_context)
        mock_bot.ask.assert_not_called()
        mock_context.send_activity.assert_not_called()


class TestParrotM365AgentHandleMessage:
    @pytest.mark.asyncio
    async def test_text_stripped(self, agent, mock_context, mock_bot):
        """Text is stripped of leading/trailing whitespace before ask()."""
        mock_context.activity.text = "  Hello  "
        await agent._handle_message(mock_context)
        mock_bot.ask.assert_called_once_with(
            question="Hello",
            session_id="conv-456",
            user_id="user-123",
            # FEAT-264: ask() also receives the request context and the caller
            # PermissionContext so the broker seam can resolve per-user creds.
            ctx=ANY,
            permission_context=ANY,
        )

    @pytest.mark.asyncio
    async def test_no_from_property(self, agent, mock_context, mock_bot):
        """Missing from_property falls back to the 'anonymous' user id (no crash)."""
        mock_context.activity.from_property = None
        await agent._handle_message(mock_context)
        mock_bot.ask.assert_called_once()
        call_kwargs = mock_bot.ask.call_args.kwargs
        # _extract_user_id() guarantees a non-empty id; with no from_property it
        # returns the "anonymous" sentinel rather than None.
        assert call_kwargs["user_id"] == "anonymous"

    @pytest.mark.asyncio
    async def test_no_conversation(self, agent, mock_context, mock_bot):
        """Missing conversation results in session_id=None (no crash)."""
        mock_context.activity.conversation = None
        await agent._handle_message(mock_context)
        call_kwargs = mock_bot.ask.call_args.kwargs
        assert call_kwargs["session_id"] is None

    @pytest.mark.asyncio
    async def test_response_content_stringified(self, agent, mock_context, mock_bot):
        """Response content is always sent as a string."""
        mock_bot.ask.return_value = MagicMock(content=42)
        await agent._handle_message(mock_context)
        mock_context.send_activity.assert_called_once()
        assert _sent_text(mock_context) == "42"
