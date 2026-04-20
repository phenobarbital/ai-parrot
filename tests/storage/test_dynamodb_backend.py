"""Unit tests for ConversationDynamoDB backend (TASK-718).

All tests use mocked aioboto3 to avoid requiring a real DynamoDB instance.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.storage.dynamodb import ConversationDynamoDB


@pytest.fixture
def dynamo_params():
    return {
        "region_name": "us-east-1",
        "endpoint_url": "http://localhost:8000",
    }


@pytest.fixture
def dynamo_backend(dynamo_params):
    return ConversationDynamoDB(
        conversations_table="test-conversations",
        artifacts_table="test-artifacts",
        dynamo_params=dynamo_params,
    )


def _make_mock_table():
    """Create a mock DynamoDB table with standard methods."""
    table = AsyncMock()
    table.put_item = AsyncMock(return_value={})
    table.get_item = AsyncMock(return_value={})
    table.delete_item = AsyncMock(return_value={})
    table.update_item = AsyncMock(return_value={})
    table.query = AsyncMock(return_value={"Items": []})
    table.batch_writer = MagicMock()
    # batch_writer returns an async context manager
    bw = AsyncMock()
    bw.delete_item = AsyncMock()
    bw.__aenter__ = AsyncMock(return_value=bw)
    bw.__aexit__ = AsyncMock(return_value=False)
    table.batch_writer.return_value = bw
    return table


class TestHelpers:
    """Tests for static helper methods."""

    def test_build_pk(self):
        pk = ConversationDynamoDB._build_pk("u123", "sales-bot")
        assert pk == "USER#u123#AGENT#sales-bot"

    def test_build_pk_special_chars(self):
        pk = ConversationDynamoDB._build_pk("user@example.com", "my-agent")
        assert pk == "USER#user@example.com#AGENT#my-agent"

    def test_ttl_epoch_positive(self):
        now = datetime(2025, 4, 16, 12, 0, 0)
        ttl = ConversationDynamoDB._ttl_epoch(now, days=180)
        assert ttl > 0
        assert ttl > int(now.timestamp())

    def test_ttl_epoch_180_days(self):
        from datetime import timedelta
        now = datetime(2025, 4, 16, 12, 0, 0)
        ttl = ConversationDynamoDB._ttl_epoch(now, days=180)
        expected = int((now + timedelta(days=180)).timestamp())
        assert ttl == expected


class TestGracefulDegradation:
    """Tests for graceful degradation when DynamoDB is unavailable."""

    @pytest.mark.asyncio
    async def test_not_initialized_query_threads(self, dynamo_backend):
        result = await dynamo_backend.query_threads("u1", "agent1")
        assert result == []

    @pytest.mark.asyncio
    async def test_not_initialized_query_turns(self, dynamo_backend):
        result = await dynamo_backend.query_turns("u1", "agent1", "sess1")
        assert result == []

    @pytest.mark.asyncio
    async def test_not_initialized_put_turn(self, dynamo_backend):
        # Should not raise
        await dynamo_backend.put_turn("u1", "agent1", "sess1", "t001", {})

    @pytest.mark.asyncio
    async def test_not_initialized_put_thread(self, dynamo_backend):
        await dynamo_backend.put_thread("u1", "agent1", "sess1", {})

    @pytest.mark.asyncio
    async def test_not_initialized_get_artifact(self, dynamo_backend):
        result = await dynamo_backend.get_artifact("u1", "agent1", "sess1", "art1")
        assert result is None

    @pytest.mark.asyncio
    async def test_not_initialized_query_artifacts(self, dynamo_backend):
        result = await dynamo_backend.query_artifacts("u1", "agent1", "sess1")
        assert result == []

    @pytest.mark.asyncio
    async def test_not_initialized_delete_thread_cascade(self, dynamo_backend):
        result = await dynamo_backend.delete_thread_cascade("u1", "agent1", "sess1")
        assert result == 0

    @pytest.mark.asyncio
    async def test_not_initialized_delete_session_artifacts(self, dynamo_backend):
        result = await dynamo_backend.delete_session_artifacts("u1", "agent1", "sess1")
        assert result == 0

    @pytest.mark.asyncio
    async def test_is_connected_false_when_not_initialized(self, dynamo_backend):
        assert dynamo_backend.is_connected is False


class TestPutTurn:
    """Tests for put_turn method."""

    @pytest.mark.asyncio
    async def test_constructs_correct_keys(self, dynamo_backend):
        mock_table = _make_mock_table()
        dynamo_backend._conv_table = mock_table
        dynamo_backend._art_table = _make_mock_table()

        await dynamo_backend.put_turn("u1", "agent1", "sess1", "t001", {
            "user_message": "hello",
            "assistant_response": "hi",
        })

        mock_table.put_item.assert_called_once()
        item = mock_table.put_item.call_args.kwargs["Item"]
        assert item["PK"] == "USER#u1#AGENT#agent1"
        assert item["SK"] == "THREAD#sess1#TURN#t001"
        assert item["type"] == "turn"
        assert item["session_id"] == "sess1"
        assert item["turn_id"] == "t001"
        assert "ttl" in item
        assert item["user_message"] == "hello"

    @pytest.mark.asyncio
    async def test_ttl_is_set(self, dynamo_backend):
        mock_table = _make_mock_table()
        dynamo_backend._conv_table = mock_table
        dynamo_backend._art_table = _make_mock_table()

        now = datetime(2025, 4, 16, 12, 0, 0)
        await dynamo_backend.put_turn("u1", "agent1", "sess1", "t001", {
            "timestamp": now,
        })

        item = mock_table.put_item.call_args.kwargs["Item"]
        expected_ttl = ConversationDynamoDB._ttl_epoch(now, 180)
        assert item["ttl"] == expected_ttl

    @pytest.mark.asyncio
    async def test_handles_exception(self, dynamo_backend):
        from botocore.exceptions import ClientError
        mock_table = _make_mock_table()
        mock_table.put_item.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "Internal"}}, "PutItem"
        )
        dynamo_backend._conv_table = mock_table
        dynamo_backend._art_table = _make_mock_table()

        # Should not raise
        await dynamo_backend.put_turn("u1", "agent1", "sess1", "t001", {})


class TestPutThread:
    """Tests for put_thread method."""

    @pytest.mark.asyncio
    async def test_constructs_correct_keys(self, dynamo_backend):
        mock_table = _make_mock_table()
        dynamo_backend._conv_table = mock_table
        dynamo_backend._art_table = _make_mock_table()

        now = datetime(2025, 4, 16, 12, 0, 0)
        await dynamo_backend.put_thread("u1", "agent1", "sess1", {
            "title": "My Thread",
            "created_at": now,
            "updated_at": now,
        })

        item = mock_table.put_item.call_args.kwargs["Item"]
        assert item["PK"] == "USER#u1#AGENT#agent1"
        assert item["SK"] == "THREAD#sess1"
        assert item["type"] == "thread"
        assert item["title"] == "My Thread"
        assert "ttl" in item


class TestUpdateThread:
    """Tests for update_thread method."""

    @pytest.mark.asyncio
    async def test_builds_update_expression(self, dynamo_backend):
        mock_table = _make_mock_table()
        dynamo_backend._conv_table = mock_table
        dynamo_backend._art_table = _make_mock_table()

        await dynamo_backend.update_thread(
            "u1", "agent1", "sess1",
            title="Updated Title",
            turn_count=5,
        )

        mock_table.update_item.assert_called_once()
        call_kwargs = mock_table.update_item.call_args.kwargs
        assert "UpdateExpression" in call_kwargs
        assert "SET" in call_kwargs["UpdateExpression"]

    @pytest.mark.asyncio
    async def test_no_updates_skips(self, dynamo_backend):
        mock_table = _make_mock_table()
        dynamo_backend._conv_table = mock_table
        dynamo_backend._art_table = _make_mock_table()

        await dynamo_backend.update_thread("u1", "agent1", "sess1")
        mock_table.update_item.assert_not_called()


class TestQueryThreads:
    """Tests for query_threads method."""

    @pytest.mark.asyncio
    async def test_returns_items(self, dynamo_backend):
        mock_table = _make_mock_table()
        mock_table.query.return_value = {
            "Items": [
                {"PK": "USER#u1#AGENT#agent1", "SK": "THREAD#sess1", "type": "thread", "title": "T1"},
                {"PK": "USER#u1#AGENT#agent1", "SK": "THREAD#sess2", "type": "thread", "title": "T2"},
            ]
        }
        dynamo_backend._conv_table = mock_table
        dynamo_backend._art_table = _make_mock_table()

        result = await dynamo_backend.query_threads("u1", "agent1")
        assert len(result) == 2
        assert result[0]["title"] == "T1"


class TestQueryTurns:
    """Tests for query_turns method."""

    @pytest.mark.asyncio
    async def test_returns_items_newest_first(self, dynamo_backend):
        mock_table = _make_mock_table()
        mock_table.query.return_value = {
            "Items": [
                {"SK": "THREAD#s1#TURN#002", "user_message": "second"},
                {"SK": "THREAD#s1#TURN#001", "user_message": "first"},
            ]
        }
        dynamo_backend._conv_table = mock_table
        dynamo_backend._art_table = _make_mock_table()

        result = await dynamo_backend.query_turns("u1", "agent1", "s1", limit=10)
        assert len(result) == 2

        # Verify ScanIndexForward=False for newest first
        call_kwargs = mock_table.query.call_args.kwargs
        assert call_kwargs["ScanIndexForward"] is False


class TestDeleteThreadCascade:
    """Tests for delete_thread_cascade method."""

    @pytest.mark.asyncio
    async def test_deletes_all_items(self, dynamo_backend):
        mock_table = _make_mock_table()
        mock_table.query.return_value = {
            "Items": [
                {"PK": "USER#u1#AGENT#a1", "SK": "THREAD#sess1"},
                {"PK": "USER#u1#AGENT#a1", "SK": "THREAD#sess1#TURN#001"},
                {"PK": "USER#u1#AGENT#a1", "SK": "THREAD#sess1#TURN#002"},
            ]
        }
        dynamo_backend._conv_table = mock_table
        dynamo_backend._art_table = _make_mock_table()

        deleted = await dynamo_backend.delete_thread_cascade("u1", "a1", "sess1")
        assert deleted == 3


class TestArtifactCRUD:
    """Tests for artifact CRUD methods."""

    @pytest.mark.asyncio
    async def test_put_artifact_keys(self, dynamo_backend):
        mock_table = _make_mock_table()
        dynamo_backend._art_table = mock_table
        dynamo_backend._conv_table = _make_mock_table()

        now = datetime(2025, 4, 16, 12, 0, 0)
        await dynamo_backend.put_artifact("u1", "agent1", "sess1", "chart-x1", {
            "artifact_type": "chart",
            "title": "Test Chart",
            "updated_at": now,
        })

        item = mock_table.put_item.call_args.kwargs["Item"]
        assert item["PK"] == "USER#u1#AGENT#agent1"
        assert item["SK"] == "THREAD#sess1#chart-x1"
        assert item["type"] == "artifact"
        assert "ttl" in item

    @pytest.mark.asyncio
    async def test_get_artifact_found(self, dynamo_backend):
        mock_table = _make_mock_table()
        mock_table.get_item.return_value = {
            "Item": {"PK": "PK", "SK": "SK", "title": "Chart"}
        }
        dynamo_backend._art_table = mock_table
        dynamo_backend._conv_table = _make_mock_table()

        result = await dynamo_backend.get_artifact("u1", "agent1", "sess1", "chart-x1")
        assert result is not None
        assert result["title"] == "Chart"

    @pytest.mark.asyncio
    async def test_get_artifact_not_found(self, dynamo_backend):
        mock_table = _make_mock_table()
        mock_table.get_item.return_value = {}
        dynamo_backend._art_table = mock_table
        dynamo_backend._conv_table = _make_mock_table()

        result = await dynamo_backend.get_artifact("u1", "agent1", "sess1", "nope")
        assert result is None

    @pytest.mark.asyncio
    async def test_query_artifacts(self, dynamo_backend):
        mock_table = _make_mock_table()
        mock_table.query.return_value = {
            "Items": [
                {"artifact_id": "chart-1", "title": "Chart 1"},
                {"artifact_id": "infog-1", "title": "Infographic 1"},
            ]
        }
        dynamo_backend._art_table = mock_table
        dynamo_backend._conv_table = _make_mock_table()

        result = await dynamo_backend.query_artifacts("u1", "agent1", "sess1")
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_delete_artifact(self, dynamo_backend):
        mock_table = _make_mock_table()
        dynamo_backend._art_table = mock_table
        dynamo_backend._conv_table = _make_mock_table()

        await dynamo_backend.delete_artifact("u1", "agent1", "sess1", "chart-x1")
        mock_table.delete_item.assert_called_once()
        key = mock_table.delete_item.call_args.kwargs["Key"]
        assert key["PK"] == "USER#u1#AGENT#agent1"
        assert key["SK"] == "THREAD#sess1#chart-x1"

    @pytest.mark.asyncio
    async def test_delete_session_artifacts(self, dynamo_backend):
        mock_table = _make_mock_table()
        mock_table.query.return_value = {
            "Items": [
                {"PK": "PK", "SK": "THREAD#sess1#chart-1"},
                {"PK": "PK", "SK": "THREAD#sess1#infog-1"},
            ]
        }
        dynamo_backend._art_table = mock_table
        dynamo_backend._conv_table = _make_mock_table()

        deleted = await dynamo_backend.delete_session_artifacts("u1", "agent1", "sess1")
        assert deleted == 2
