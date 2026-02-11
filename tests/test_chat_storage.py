"""Unit tests for parrot.storage (ChatStorage + models).

All Redis and DocumentDB interactions are mocked.
"""

import asyncio
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from parrot.storage.models import (
    ChatMessage,
    Conversation,
    MessageRole,
    Source,
    ToolCall,
)
from parrot.storage.chat import (
    ChatStorage,
    CONVERSATIONS_COLLECTION,
    MESSAGES_COLLECTION,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def mock_redis():
    """Mocked RedisConversation instance."""
    redis = AsyncMock()
    redis.get_history = AsyncMock(return_value=None)
    redis.create_history = AsyncMock()
    redis.add_turn = AsyncMock()
    redis.delete_history = AsyncMock(return_value=True)
    redis.close = AsyncMock()
    return redis


@pytest_asyncio.fixture
async def mock_docdb():
    """Mocked DocumentDb instance that supports async context manager."""
    db_inner = AsyncMock()
    # read returns empty list by default
    db_inner.read = AsyncMock(return_value=[])
    db_inner.write = AsyncMock()
    db_inner.create_indexes = AsyncMock()

    # Mock collection access for find/update/delete
    mock_collection = AsyncMock()
    mock_collection.update_one = AsyncMock()
    mock_collection.delete_many = AsyncMock()

    # Simulate async cursor (find().sort().limit()) returning empty list
    mock_cursor = AsyncMock()
    mock_cursor.__aiter__ = MagicMock(return_value=iter([]))
    mock_collection.find = MagicMock(return_value=mock_collection)
    mock_collection.sort = MagicMock(return_value=mock_collection)
    mock_collection.limit = MagicMock(return_value=mock_cursor)

    db_inner._db = MagicMock()
    db_inner._db.get_collection = MagicMock(return_value=mock_collection)

    docdb = AsyncMock()
    docdb.__aenter__ = AsyncMock(return_value=db_inner)
    docdb.__aexit__ = AsyncMock(return_value=False)
    docdb.close = AsyncMock()

    # Expose inner mock for assertions
    docdb._inner = db_inner
    docdb._collection = mock_collection
    return docdb


@pytest_asyncio.fixture
async def storage(mock_redis, mock_docdb):
    """ChatStorage wired with mocked backends."""
    s = ChatStorage(redis_conversation=mock_redis, document_db=mock_docdb)
    s._initialized = True
    return s


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestChatMessage:
    """Verify ChatMessage serialization round-trip."""

    def test_to_dict_and_back(self):
        msg = ChatMessage(
            message_id="m1",
            session_id="s1",
            user_id="u1",
            agent_id="agent_a",
            role=MessageRole.USER.value,
            content="Hello",
            tool_calls=[ToolCall(name="grep", status="completed")],
            sources=[Source(content="src", metadata={"page": 1})],
        )
        d = msg.to_dict()
        assert d["message_id"] == "m1"
        assert d["role"] == "user"
        assert len(d["tool_calls"]) == 1
        assert d["tool_calls"][0]["name"] == "grep"

        restored = ChatMessage.from_dict(d)
        assert restored.message_id == msg.message_id
        assert restored.role == msg.role
        assert len(restored.tool_calls) == 1
        assert restored.tool_calls[0].name == "grep"

    def test_defaults(self):
        msg = ChatMessage(
            message_id="m2",
            session_id="s2",
            user_id="u2",
            agent_id="a2",
            role=MessageRole.ASSISTANT.value,
            content="Hi",
        )
        d = msg.to_dict()
        assert d["tool_calls"] == []
        assert d["sources"] == []
        assert d["output"] is None


class TestConversation:
    """Verify Conversation serialization round-trip."""

    def test_to_dict_and_back(self):
        conv = Conversation(
            session_id="s1",
            user_id="u1",
            agent_id="agent_a",
            title="Test conversation",
            message_count=4,
            model="claude-3.5",
        )
        d = conv.to_dict()
        assert d["session_id"] == "s1"
        assert d["message_count"] == 4

        restored = Conversation.from_dict(d)
        assert restored.session_id == conv.session_id
        assert restored.model == "claude-3.5"


class TestToolCall:
    """Verify ToolCall serialization."""

    def test_round_trip(self):
        tc = ToolCall(
            name="search",
            status="completed",
            output="found 3 results",
            arguments={"query": "test"},
        )
        d = tc.to_dict()
        restored = ToolCall.from_dict(d)
        assert restored.name == "search"
        assert restored.output == "found 3 results"


# ---------------------------------------------------------------------------
# ChatStorage tests
# ---------------------------------------------------------------------------

class TestChatStorageSaveTurn:
    """Verify save_turn writes to Redis and schedules DocumentDB write."""

    @pytest.mark.asyncio
    async def test_save_turn_creates_history_when_missing(self, storage, mock_redis):
        mock_redis.get_history.return_value = None  # no existing history

        turn_id = await storage.save_turn(
            user_id="u1",
            session_id="s1",
            agent_id="agent_a",
            user_message="Hello",
            assistant_response="Hi there",
        )

        assert turn_id  # non-empty string
        mock_redis.create_history.assert_awaited_once()
        mock_redis.add_turn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_save_turn_appends_to_existing_history(self, storage, mock_redis):
        mock_redis.get_history.return_value = MagicMock(turns=[])  # existing

        turn_id = await storage.save_turn(
            user_id="u1",
            session_id="s1",
            agent_id="agent_a",
            user_message="Hello",
            assistant_response="Hi there",
        )

        assert turn_id
        mock_redis.create_history.assert_not_awaited()
        mock_redis.add_turn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_save_turn_with_tool_calls_and_sources(self, storage, mock_redis):
        await storage.save_turn(
            user_id="u1",
            session_id="s1",
            agent_id="agent_a",
            user_message="Lookup data",
            assistant_response="Found it",
            tool_calls=[{"name": "sql_query", "status": "completed"}],
            sources=[{"content": "table_a", "metadata": {}}],
            model="claude-3.5",
            provider="anthropic",
        )

        # Verify the ConversationTurn passed to add_turn
        call_args = mock_redis.add_turn.call_args
        turn = call_args.args[2] if len(call_args.args) > 2 else call_args.kwargs.get('turn')
        assert turn.tools_used == ["sql_query"]
        assert turn.metadata["model"] == "claude-3.5"


class TestChatStorageLoadConversation:
    """Verify load_conversation reads Redis-first, then DocumentDB."""

    @pytest.mark.asyncio
    async def test_load_from_redis(self, storage, mock_redis):
        from parrot.memory.abstract import ConversationHistory, ConversationTurn

        history = ConversationHistory(
            session_id="s1",
            user_id="u1",
            turns=[
                ConversationTurn(
                    turn_id="t1",
                    user_id="u1",
                    user_message="Hello",
                    assistant_response="Hi",
                )
            ],
        )
        mock_redis.get_history.return_value = history

        messages = await storage.load_conversation("u1", "s1")
        assert len(messages) == 2  # user + assistant
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_load_falls_back_to_docdb_when_redis_empty(self, storage, mock_redis, mock_docdb):
        mock_redis.get_history.return_value = None

        # DocumentDB returns empty list (mocked cursor)
        messages = await storage.load_conversation("u1", "s1")
        assert messages == []


class TestChatStorageDeleteConversation:
    """Verify delete removes from both stores."""

    @pytest.mark.asyncio
    async def test_delete_conversation(self, storage, mock_redis, mock_docdb):
        deleted = await storage.delete_conversation("u1", "s1")
        assert deleted is True
        mock_redis.delete_history.assert_awaited_once()


class TestChatStorageListConversations:
    """Verify list_user_conversations queries DocumentDB."""

    @pytest.mark.asyncio
    async def test_list_empty(self, storage):
        conversations = await storage.list_user_conversations("u1")
        assert conversations == []


class TestChatStorageEnsureIndexes:
    """Verify that initialize creates DocumentDB indexes."""

    @pytest.mark.asyncio
    async def test_ensure_indexes_called(self, mock_redis, mock_docdb):
        s = ChatStorage(redis_conversation=mock_redis, document_db=mock_docdb)
        await s.initialize()

        inner = mock_docdb._inner
        assert inner.create_indexes.await_count == 2  # conversations + messages


class TestChatStorageGetContext:
    """Verify get_context_for_agent returns LLM-formatted messages."""

    @pytest.mark.asyncio
    async def test_context_from_redis(self, storage, mock_redis):
        from parrot.memory.abstract import ConversationHistory, ConversationTurn

        history = ConversationHistory(
            session_id="s1",
            user_id="u1",
            turns=[
                ConversationTurn(
                    turn_id="t1",
                    user_id="u1",
                    user_message="What is X?",
                    assistant_response="X is Y.",
                )
            ],
        )
        mock_redis.get_history.return_value = history

        context = await storage.get_context_for_agent("u1", "s1")
        assert len(context) == 2
        assert context[0]["role"] == "user"
        assert context[1]["role"] == "assistant"
