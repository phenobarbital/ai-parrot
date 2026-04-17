"""Unit tests for ChatStorage DynamoDB migration (TASK-722).

All tests use mocked DynamoDB and Redis backends.
"""

import asyncio
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.storage.chat import ChatStorage


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get_history = AsyncMock(return_value=None)
    redis.create_history = AsyncMock()
    redis.add_turn = AsyncMock()
    redis.delete_history = AsyncMock(return_value=True)
    redis.close = AsyncMock()
    return redis


@pytest.fixture
def mock_dynamo():
    dynamo = AsyncMock()
    dynamo.put_turn = AsyncMock()
    dynamo.put_thread = AsyncMock()
    dynamo.update_thread = AsyncMock()
    dynamo.query_threads = AsyncMock(return_value=[])
    dynamo.query_turns = AsyncMock(return_value=[])
    dynamo.delete_thread_cascade = AsyncMock(return_value=0)
    dynamo.delete_session_artifacts = AsyncMock(return_value=0)
    dynamo.close = AsyncMock()
    dynamo.initialize = AsyncMock()
    dynamo._build_pk = MagicMock(side_effect=lambda u, a: f"USER#{u}#AGENT#{a}")
    dynamo._conv_table = AsyncMock()
    dynamo._conv_table.delete_item = AsyncMock()
    return dynamo


@pytest.fixture
def storage(mock_redis, mock_dynamo):
    s = ChatStorage(redis_conversation=mock_redis, dynamodb=mock_dynamo)
    s._initialized = True
    return s


class TestSaveTurn:
    """Tests for save_turn with DynamoDB backend."""

    @pytest.mark.asyncio
    async def test_returns_turn_id(self, storage):
        turn_id = await storage.save_turn(
            user_id="u1",
            session_id="sess1",
            agent_id="bot1",
            user_message="hello",
            assistant_response="hi",
        )
        assert turn_id is not None
        assert len(turn_id) > 0

    @pytest.mark.asyncio
    async def test_uses_provided_turn_id(self, storage):
        turn_id = await storage.save_turn(
            turn_id="custom-123",
            user_id="u1",
            session_id="sess1",
            agent_id="bot1",
            user_message="hello",
            assistant_response="hi",
        )
        assert turn_id == "custom-123"

    @pytest.mark.asyncio
    async def test_fires_dynamodb_background_task(self, storage, mock_dynamo):
        turn_id = await storage.save_turn(
            user_id="u1",
            session_id="sess1",
            agent_id="bot1",
            user_message="hello",
            assistant_response="hi",
        )
        # Allow background task to run
        await asyncio.sleep(0.05)

        # The background task should have called put_turn
        mock_dynamo.put_turn.assert_called_once()
        call_kwargs = mock_dynamo.put_turn.call_args.kwargs
        assert call_kwargs["user_id"] == "u1"
        assert call_kwargs["agent_id"] == "bot1"
        assert call_kwargs["session_id"] == "sess1"
        data = call_kwargs["data"]
        assert data["user_message"] == "hello"
        assert data["assistant_response"] == "hi"


class TestLoadConversation:
    """Tests for load_conversation with DynamoDB fallback."""

    @pytest.mark.asyncio
    async def test_falls_back_to_dynamodb(self, storage, mock_dynamo, mock_redis):
        mock_redis.get_history.return_value = None
        mock_dynamo.query_turns.return_value = [
            {
                "turn_id": "t001",
                "user_message": "hello",
                "assistant_response": "hi",
                "timestamp": "2025-04-16T12:00:00",
            },
        ]

        messages = await storage.load_conversation("u1", "sess1", agent_id="bot1")
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "hello"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "hi"

    @pytest.mark.asyncio
    async def test_empty_when_no_backend(self):
        s = ChatStorage()
        s._initialized = True
        messages = await s.load_conversation("u1", "sess1")
        assert messages == []


class TestListUserConversations:
    """Tests for list_user_conversations with DynamoDB."""

    @pytest.mark.asyncio
    async def test_returns_thread_metadata(self, storage, mock_dynamo):
        mock_dynamo.query_threads.return_value = [
            {
                "PK": "USER#u1#AGENT#bot1",
                "SK": "THREAD#sess1",
                "type": "thread",
                "ttl": 12345,
                "session_id": "sess1",
                "title": "Chat 1",
                "updated_at": "2025-04-16T12:00:00",
            },
        ]

        results = await storage.list_user_conversations("u1", agent_id="bot1")
        assert len(results) == 1
        assert results[0]["session_id"] == "sess1"
        assert results[0]["title"] == "Chat 1"
        # DynamoDB internal fields should be stripped
        assert "PK" not in results[0]
        assert "SK" not in results[0]
        assert "type" not in results[0]
        assert "ttl" not in results[0]

    @pytest.mark.asyncio
    async def test_empty_when_no_dynamo(self):
        s = ChatStorage()
        s._initialized = True
        results = await s.list_user_conversations("u1")
        assert results == []


class TestCreateConversation:
    """Tests for create_conversation with DynamoDB."""

    @pytest.mark.asyncio
    async def test_creates_thread(self, storage, mock_dynamo):
        result = await storage.create_conversation("u1", "sess1", "bot1", "My Chat")
        assert result is not None
        assert result["session_id"] == "sess1"
        assert result["title"] == "My Chat"
        mock_dynamo.put_thread.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_none_when_no_dynamo(self):
        s = ChatStorage()
        s._initialized = True
        result = await s.create_conversation("u1", "sess1", "bot1")
        assert result is None


class TestUpdateConversationTitle:
    """Tests for update_conversation_title with DynamoDB."""

    @pytest.mark.asyncio
    async def test_updates_thread(self, storage, mock_dynamo):
        result = await storage.update_conversation_title(
            "sess1", "New Title", user_id="u1", agent_id="bot1"
        )
        assert result is True
        mock_dynamo.update_thread.assert_called_once()
        call_kwargs = mock_dynamo.update_thread.call_args.kwargs
        assert call_kwargs["title"] == "New Title"

    @pytest.mark.asyncio
    async def test_returns_false_without_user_id(self, storage):
        result = await storage.update_conversation_title("sess1", "New Title")
        assert result is False


class TestDeleteConversation:
    """Tests for delete_conversation with DynamoDB cascade."""

    @pytest.mark.asyncio
    async def test_cascade_deletes_both_tables(self, storage, mock_dynamo):
        mock_dynamo.delete_thread_cascade.return_value = 3
        mock_dynamo.delete_session_artifacts.return_value = 2

        result = await storage.delete_conversation("u1", "sess1", agent_id="bot1")
        assert result is True
        mock_dynamo.delete_thread_cascade.assert_called_once()
        mock_dynamo.delete_session_artifacts.assert_called_once()

    @pytest.mark.asyncio
    async def test_redis_delete_also_called(self, storage, mock_redis):
        result = await storage.delete_conversation("u1", "sess1", agent_id="bot1")
        assert result is True
        mock_redis.delete_history.assert_called_once()


class TestDeleteTurn:
    """Tests for delete_turn with DynamoDB."""

    @pytest.mark.asyncio
    async def test_deletes_turn(self, storage, mock_dynamo):
        result = await storage.delete_turn(
            "sess1", "t001", user_id="u1", agent_id="bot1"
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_without_user_id(self, storage):
        result = await storage.delete_turn("sess1", "t001")
        assert result is False


class TestBackwardCompatibility:
    """Tests for backward compatibility."""

    def test_accepts_document_db_param(self):
        """ChatStorage still accepts document_db parameter."""
        mock_docdb = MagicMock()
        s = ChatStorage(document_db=mock_docdb)
        assert s._docdb is mock_docdb

    def test_accepts_dynamodb_param(self):
        """ChatStorage accepts dynamodb parameter."""
        mock_dynamo = MagicMock()
        s = ChatStorage(dynamodb=mock_dynamo)
        assert s._dynamo is mock_dynamo
