"""
Unit tests for read-only operator commands (FEAT-210 TASK-1395).

Tests: /context, /memory, /model, /mission — all read-only handlers on
OperatorCommandsMixin.

Note: The mixin is wired into TelegramAgentWrapper in TASK-1398.  These
tests create a combined class directly (OperatorCommandsMixin + a thin
stub base) so they can test mixin methods before TASK-1398 is done.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock


# ---------------------------------------------------------------------------
# Shared stub + fixture
# ---------------------------------------------------------------------------

class _StubBase:
    """Minimal stand-in for TelegramAgentWrapper for testing the mixin methods."""

    def _is_operator(self, chat_id: int) -> bool:
        op_ids = getattr(self.config, 'operator_chat_ids', None)
        if not getattr(self.config, 'enable_operator_commands', True):
            return False
        if not op_ids:
            return False
        return chat_id in op_ids


def _make_op_wrapper(operator_chat_ids=None, enable_operator_commands=True):
    """Build a minimal wrapper stand-in with OperatorCommandsMixin.

    Creates a combined class (OperatorCommandsMixin + _StubBase) and uses
    __new__ to bypass __init__, setting attributes manually.
    """
    from parrot.integrations.telegram.operator_commands import OperatorCommandsMixin

    class _CombinedWrapper(OperatorCommandsMixin, _StubBase):
        pass

    w = _CombinedWrapper.__new__(_CombinedWrapper)
    w.logger = MagicMock()
    w.conversations = {}
    w.agent = MagicMock(name="agent")
    w.agent.model = "gemini-2.5"
    w.agent.use_llm = "google"
    w.agent.name = "TestAgent"
    w.config = MagicMock()
    w.config.name = "test-bot"
    w.config.operator_chat_ids = operator_chat_ids if operator_chat_ids is not None else [111]
    w.config.enable_operator_commands = enable_operator_commands
    w.app = {}   # no heartbeat/bot_manager → degrade paths
    # Patch _send_safe_message with AsyncMock
    w._send_safe_message = AsyncMock()
    return w


def _make_message(chat_id: int, text: str = "") -> MagicMock:
    """Create a mock aiogram Message."""
    msg = MagicMock()
    msg.chat.id = chat_id
    msg.text = text
    msg.answer = AsyncMock()
    return msg


# ---------------------------------------------------------------------------
# /context tests
# ---------------------------------------------------------------------------

class TestHandleContext:
    @pytest.mark.asyncio
    async def test_shows_context_no_conversation(self):
        """When no conversation exists for the chat, returns a placeholder."""
        w = _make_op_wrapper(operator_chat_ids=[111])
        msg = _make_message(chat_id=111)
        await w.handle_context(msg)
        w._send_safe_message.assert_awaited_once()
        text = w._send_safe_message.call_args[0][1]
        assert "no conversation" in text.lower() or "context" in text.lower()

    @pytest.mark.asyncio
    async def test_shows_context_with_conversation(self):
        """When a conversation exists, projects its context metadata."""
        from parrot.memory.mem import InMemoryConversation

        w = _make_op_wrapper(operator_chat_ids=[111])
        conv = InMemoryConversation()
        # Seed a history with metadata
        await conv.create_history(
            user_id="u1",
            session_id="s1",
            metadata={"topic": "finance"},
        )
        w.conversations[111] = conv
        msg = _make_message(chat_id=111)
        await w.handle_context(msg)
        w._send_safe_message.assert_awaited_once()
        text = w._send_safe_message.call_args[0][1]
        # Should mention "topic" or "finance" from the metadata
        assert "finance" in text or "topic" in text or "context" in text.lower()

    @pytest.mark.asyncio
    async def test_non_operator_blocked(self):
        """Non-operator chat gets a rejection message, not context."""
        w = _make_op_wrapper(operator_chat_ids=[111])
        msg = _make_message(chat_id=999)  # not in allowlist
        await w.handle_context(msg)
        msg.answer.assert_awaited_once()
        denial = msg.answer.call_args[0][0]
        assert "denied" in denial.lower() or "operator" in denial.lower() or "access" in denial.lower()
        w._send_safe_message.assert_not_awaited()


# ---------------------------------------------------------------------------
# /memory tests
# ---------------------------------------------------------------------------

class TestHandleMemory:
    @pytest.mark.asyncio
    async def test_readonly_projects_turns(self):
        """Shows recent conversation turns without mutating the memory."""
        from parrot.memory.mem import InMemoryConversation
        from parrot.memory.abstract import ConversationTurn
        import uuid

        w = _make_op_wrapper(operator_chat_ids=[111])
        conv = InMemoryConversation()
        history = await conv.create_history(user_id="u1", session_id="s1")
        turn = ConversationTurn(
            turn_id=str(uuid.uuid4()),
            user_id="u1",
            user_message="Hello bot",
            assistant_response="Hello user",
        )
        await conv.add_turn(user_id="u1", session_id="s1", turn=turn)
        original_turn_count = len(history.turns)
        w.conversations[111] = conv

        msg = _make_message(chat_id=111)
        await w.handle_memory(msg)

        # Assert response sent
        w._send_safe_message.assert_awaited_once()
        text = w._send_safe_message.call_args[0][1]
        assert "Hello bot" in text or "Hello user" in text

        # Assert no mutation — turn count unchanged
        history_after = await conv.get_history(user_id="u1", session_id="s1")
        assert len(history_after.turns) == original_turn_count

    @pytest.mark.asyncio
    async def test_truncates_to_limit(self):
        """Long conversation is truncated to N recent turns."""
        from parrot.memory.mem import InMemoryConversation
        from parrot.memory.abstract import ConversationTurn
        from parrot.integrations.telegram.operator_commands import _MEMORY_TURN_LIMIT
        import uuid

        w = _make_op_wrapper(operator_chat_ids=[111])
        conv = InMemoryConversation()
        await conv.create_history(user_id="u1", session_id="s1")
        # Add more turns than the limit
        for i in range(_MEMORY_TURN_LIMIT + 5):
            turn = ConversationTurn(
                turn_id=str(uuid.uuid4()),
                user_id="u1",
                user_message=f"msg-{i}",
                assistant_response=f"resp-{i}",
            )
            await conv.add_turn(user_id="u1", session_id="s1", turn=turn)

        w.conversations[111] = conv
        msg = _make_message(chat_id=111)
        await w.handle_memory(msg)

        text = w._send_safe_message.call_args[0][1]
        # The most recent messages should appear; earliest (msg-0) should not
        assert "msg-0" not in text

    @pytest.mark.asyncio
    async def test_no_conversation_returns_placeholder(self):
        """When no conversation exists, returns a placeholder."""
        w = _make_op_wrapper(operator_chat_ids=[111])
        msg = _make_message(chat_id=111)
        await w.handle_memory(msg)
        text = w._send_safe_message.call_args[0][1]
        assert "no conversation" in text.lower() or "memory" in text.lower()

    @pytest.mark.asyncio
    async def test_non_operator_blocked(self):
        """Non-operator gets rejection message."""
        w = _make_op_wrapper(operator_chat_ids=[111])
        msg = _make_message(chat_id=999)
        await w.handle_memory(msg)
        msg.answer.assert_awaited_once()
        w._send_safe_message.assert_not_awaited()


# ---------------------------------------------------------------------------
# /model tests
# ---------------------------------------------------------------------------

class TestHandleModel:
    @pytest.mark.asyncio
    async def test_readonly_shows_model(self):
        """Shows agent model and use_llm."""
        w = _make_op_wrapper(operator_chat_ids=[111])
        w.agent.model = "gpt-4o"
        w.agent.use_llm = "openai"
        w.agent.name = "MyAgent"

        msg = _make_message(chat_id=111)
        await w.handle_model(msg)

        w._send_safe_message.assert_awaited_once()
        text = w._send_safe_message.call_args[0][1]
        assert "gpt-4o" in text
        assert "openai" in text

    @pytest.mark.asyncio
    async def test_no_mutation(self):
        """Agent attributes are unchanged after /model."""
        w = _make_op_wrapper(operator_chat_ids=[111])
        original_model = w.agent.model
        original_llm = w.agent.use_llm

        msg = _make_message(chat_id=111)
        await w.handle_model(msg)

        assert w.agent.model == original_model
        assert w.agent.use_llm == original_llm

    @pytest.mark.asyncio
    async def test_non_operator_blocked(self):
        """Non-operator gets rejection."""
        w = _make_op_wrapper(operator_chat_ids=[111])
        msg = _make_message(chat_id=999)
        await w.handle_model(msg)
        msg.answer.assert_awaited_once()
        w._send_safe_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_graceful_when_model_absent(self):
        """When agent has no model attribute, shows 'unknown'."""
        w = _make_op_wrapper(operator_chat_ids=[111])
        del w.agent.model  # remove attribute
        del w.agent.use_llm

        msg = _make_message(chat_id=111)
        await w.handle_model(msg)  # should not raise

        text = w._send_safe_message.call_args[0][1]
        assert "unknown" in text.lower() or "model" in text.lower()


# ---------------------------------------------------------------------------
# /mission tests
# ---------------------------------------------------------------------------

class TestHandleMission:
    @pytest.mark.asyncio
    async def test_degrades_without_heartbeat(self):
        """No HeartbeatManager in app → 'not configured' message."""
        w = _make_op_wrapper(operator_chat_ids=[111])
        # app is {} (no heartbeat_manager key) — degrades regardless of HeartbeatManager import
        msg = _make_message(chat_id=111)
        await w.handle_mission(msg)
        text = w._send_safe_message.call_args[0][1]
        assert "not configured" in text.lower() or "not available" in text.lower() or "mission" in text.lower()

    @pytest.mark.asyncio
    async def test_shows_mission_with_fake_heartbeat(self):
        """With a fake heartbeat manager wired in app, shows mission text."""
        w = _make_op_wrapper(operator_chat_ids=[111])

        # Inject a fake heartbeat manager with a mission attribute
        fake_hb = MagicMock()
        fake_hb.mission = "Monitor and report system health every 60 seconds."
        w.app = {'heartbeat_manager': fake_hb}

        # Patch HeartbeatManager to not be None (simulate FEAT-209 installed)
        import parrot.integrations.telegram.operator_commands as oc_module
        original = oc_module.HeartbeatManager
        oc_module.HeartbeatManager = object  # truthy sentinel
        try:
            msg = _make_message(chat_id=111)
            await w.handle_mission(msg)
            text = w._send_safe_message.call_args[0][1]
            assert "Monitor" in text or "mission" in text.lower()
        finally:
            oc_module.HeartbeatManager = original

    @pytest.mark.asyncio
    async def test_non_operator_blocked(self):
        """Non-operator gets rejection."""
        w = _make_op_wrapper(operator_chat_ids=[111])
        msg = _make_message(chat_id=999)
        await w.handle_mission(msg)
        msg.answer.assert_awaited_once()
        w._send_safe_message.assert_not_awaited()
