"""Unit tests for FEAT-120 message ID tracking and per-chat message cache.

Tests verify:
- _cache_message_id stores entries with correct truncation and eviction
- _store_telegram_metadata injects IDs into ConversationTurn.metadata
- handle_message integrates cache and metadata after response
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_minimal_wrapper():
    """Create a minimal TelegramAgentWrapper with only the fields needed for these tests."""
    from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
    from parrot.integrations.telegram.models import TelegramAgentConfig

    config = TelegramAgentConfig(name="test-bot", chatbot_id="testbot")

    wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
    wrapper.config = config
    wrapper.logger = MagicMock()
    wrapper._message_id_cache = {}
    return wrapper


class TestCacheMessageId:
    """Tests for _cache_message_id helper."""

    def test_cache_stores_entry(self):
        """Message ID and truncated text stored in cache."""
        wrapper = _make_minimal_wrapper()
        wrapper._cache_message_id(1001, 42, "Hello world")
        assert wrapper._message_id_cache[1001][42] == "Hello world"

    def test_cache_truncates_text(self):
        """Text longer than 200 chars is truncated to 200."""
        wrapper = _make_minimal_wrapper()
        long_text = "x" * 300
        wrapper._cache_message_id(1001, 42, long_text)
        assert len(wrapper._message_id_cache[1001][42]) == 200

    def test_cache_eviction_at_limit(self):
        """Oldest entry evicted when cache exceeds 100 entries per chat."""
        wrapper = _make_minimal_wrapper()
        # Fill cache to limit
        for i in range(100):
            wrapper._cache_message_id(1001, i, f"message {i}")
        # Verify 100 entries
        assert len(wrapper._message_id_cache[1001]) == 100
        # First entry should be message 0
        assert 0 in wrapper._message_id_cache[1001]

        # Add one more — should evict message 0
        wrapper._cache_message_id(1001, 100, "extra message")
        assert len(wrapper._message_id_cache[1001]) == 100
        assert 0 not in wrapper._message_id_cache[1001]
        assert 100 in wrapper._message_id_cache[1001]

    def test_cache_separate_per_chat(self):
        """Different chat_ids have independent caches."""
        wrapper = _make_minimal_wrapper()
        wrapper._cache_message_id(1001, 42, "Chat 1 message")
        wrapper._cache_message_id(2002, 42, "Chat 2 message")
        assert wrapper._message_id_cache[1001][42] == "Chat 1 message"
        assert wrapper._message_id_cache[2002][42] == "Chat 2 message"

    def test_cache_initializes_per_chat(self):
        """Cache dict is created lazily per chat."""
        wrapper = _make_minimal_wrapper()
        assert 1001 not in wrapper._message_id_cache
        wrapper._cache_message_id(1001, 1, "first")
        assert 1001 in wrapper._message_id_cache

    def test_cache_empty_text(self):
        """None/empty text stored as empty string."""
        wrapper = _make_minimal_wrapper()
        wrapper._cache_message_id(1001, 5, "")
        assert wrapper._message_id_cache[1001][5] == ""


@pytest.mark.asyncio
class TestStoreTelegramMetadata:
    """Tests for _store_telegram_metadata helper."""

    async def test_metadata_injected(self):
        """Both message IDs appear in ConversationTurn.metadata."""
        from parrot.memory.abstract import ConversationTurn, ConversationHistory

        wrapper = _make_minimal_wrapper()

        turn = ConversationTurn(
            turn_id="t1",
            user_id="user123",
            user_message="hello",
            assistant_response="hi",
        )
        history = ConversationHistory(session_id="sess1", user_id="user123", turns=[turn])
        memory = MagicMock()
        memory.get_history = AsyncMock(return_value=history)

        await wrapper._store_telegram_metadata(
            memory, "user123", "sess1", 101, 202
        )

        assert turn.metadata["telegram_message_id"] == 101
        assert turn.metadata["telegram_bot_message_id"] == 202

    async def test_no_history_no_crash(self):
        """Gracefully handles memory returning None."""
        wrapper = _make_minimal_wrapper()

        memory = MagicMock()
        memory.get_history = AsyncMock(return_value=None)

        # Must not raise
        await wrapper._store_telegram_metadata(memory, "user123", "sess1", 1, 2)

    async def test_empty_turns_no_crash(self):
        """Gracefully handles history with no turns."""
        from parrot.memory.abstract import ConversationHistory

        wrapper = _make_minimal_wrapper()
        history = ConversationHistory(session_id="sess1", user_id="user123", turns=[])
        memory = MagicMock()
        memory.get_history = AsyncMock(return_value=history)

        # Must not raise
        await wrapper._store_telegram_metadata(memory, "user123", "sess1", 1, 2)

    async def test_memory_exception_logged(self):
        """Exception from memory.get_history is caught and logged as debug."""
        wrapper = _make_minimal_wrapper()

        memory = MagicMock()
        memory.get_history = AsyncMock(side_effect=RuntimeError("db error"))

        # Must not raise
        await wrapper._store_telegram_metadata(memory, "user123", "sess1", 1, 2)
        wrapper.logger.debug.assert_called()


@pytest.mark.asyncio
class TestHandleMessageIntegration:
    """Integration tests for handle_message with message ID tracking."""

    def _make_full_wrapper(self):
        """Create a wrapper with all needed mocks for handle_message testing."""
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
        from parrot.integrations.telegram.models import TelegramAgentConfig

        config = TelegramAgentConfig(name="test-bot", chatbot_id="testbot")
        agent = MagicMock()
        bot = MagicMock()

        wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
        wrapper.config = config
        wrapper.agent = agent
        wrapper.bot = bot
        wrapper.logger = MagicMock()
        wrapper._agent_lock = asyncio.Lock()
        wrapper._user_sessions = {}
        wrapper.conversations = {}
        wrapper._message_id_cache = {}
        return wrapper

    def _make_message(self, chat_id: int = 12345, text: str = "hello", msg_id: int = 100):
        """Create a mock Message."""
        message = MagicMock()
        message.chat.id = chat_id
        message.text = text
        message.message_id = msg_id
        message.from_user.id = 999
        message.answer = AsyncMock()
        return message

    async def test_message_ids_cached_after_response(self):
        """User message and bot response are both cached after agent response."""
        wrapper = self._make_full_wrapper()
        message = self._make_message(chat_id=5000, text="hello bot", msg_id=10)

        memory = MagicMock()
        session = MagicMock()
        session.user_id = "u1"
        session.session_id = "s1"

        sent_msg = MagicMock()
        sent_msg.message_id = 999

        wrapper._is_authorized = MagicMock(return_value=True)
        wrapper._check_authentication = AsyncMock(return_value=True)
        wrapper._state_manager = MagicMock()
        wrapper._state_manager.get_suspended_session = AsyncMock(return_value=None)
        wrapper._get_or_create_memory = MagicMock(return_value=memory)
        wrapper._get_user_session = MagicMock(return_value=session)
        wrapper._invoke_agent = AsyncMock(return_value="response")
        wrapper._parse_response = MagicMock(return_value=MagicMock())
        wrapper._send_parsed_response = AsyncMock(return_value=sent_msg)
        wrapper._store_telegram_metadata = AsyncMock()
        wrapper._typing_indicator = AsyncMock()

        await wrapper.handle_message(message)

        # User message (msg_id=10) must be in cache
        assert 10 in wrapper._message_id_cache.get(5000, {})
        # Bot message (msg_id=999) must be in cache
        assert 999 in wrapper._message_id_cache.get(5000, {})

    async def test_metadata_stored_after_response(self):
        """_store_telegram_metadata called with user and bot message IDs."""
        wrapper = self._make_full_wrapper()
        message = self._make_message(chat_id=5000, text="hello", msg_id=10)

        memory = MagicMock()
        session = MagicMock()
        session.user_id = "u1"
        session.session_id = "s1"

        sent_msg = MagicMock()
        sent_msg.message_id = 888

        wrapper._is_authorized = MagicMock(return_value=True)
        wrapper._check_authentication = AsyncMock(return_value=True)
        wrapper._state_manager = MagicMock()
        wrapper._state_manager.get_suspended_session = AsyncMock(return_value=None)
        wrapper._get_or_create_memory = MagicMock(return_value=memory)
        wrapper._get_user_session = MagicMock(return_value=session)
        wrapper._invoke_agent = AsyncMock(return_value="response")
        wrapper._parse_response = MagicMock(return_value=MagicMock())
        wrapper._send_parsed_response = AsyncMock(return_value=sent_msg)
        wrapper._store_telegram_metadata = AsyncMock()
        wrapper._typing_indicator = AsyncMock()

        await wrapper.handle_message(message)

        wrapper._store_telegram_metadata.assert_awaited_once_with(
            memory, "u1", "s1", 10, 888
        )
