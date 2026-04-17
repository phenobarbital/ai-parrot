"""Integration tests for FEAT-103: Agent Artifact Persistency (TASK-726).

End-to-end tests covering the full lifecycle of conversation threads,
turns, artifacts, S3 overflow, and cascade deletion.

All DynamoDB and S3 interactions are mocked — no real AWS calls.
"""

import asyncio
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from parrot.storage.dynamodb import ConversationDynamoDB
from parrot.storage.s3_overflow import S3OverflowManager
from parrot.storage.artifacts import ArtifactStore
from parrot.storage.chat import ChatStorage
from parrot.storage.models import (
    Artifact,
    ArtifactType,
    ArtifactCreator,
    ArtifactSummary,
    ThreadMetadata,
    CanvasDefinition,
    CanvasBlock,
    CanvasBlockType,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_mock_table():
    """Create a mock DynamoDB table."""
    table = AsyncMock()
    table.put_item = AsyncMock(return_value={})
    table.get_item = AsyncMock(return_value={})
    table.delete_item = AsyncMock(return_value={})
    table.update_item = AsyncMock(return_value={})
    table.query = AsyncMock(return_value={"Items": []})
    bw = AsyncMock()
    bw.delete_item = AsyncMock()
    bw.__aenter__ = AsyncMock(return_value=bw)
    bw.__aexit__ = AsyncMock(return_value=False)
    table.batch_writer = MagicMock(return_value=bw)
    return table


@pytest.fixture
def mock_dynamo():
    """Fully mocked ConversationDynamoDB for integration tests."""
    backend = AsyncMock(spec=ConversationDynamoDB)
    backend.put_thread = AsyncMock()
    backend.update_thread = AsyncMock()
    backend.query_threads = AsyncMock(return_value=[])
    backend.put_turn = AsyncMock()
    backend.query_turns = AsyncMock(return_value=[])
    backend.delete_thread_cascade = AsyncMock(return_value=0)
    backend.put_artifact = AsyncMock()
    backend.get_artifact = AsyncMock(return_value=None)
    backend.query_artifacts = AsyncMock(return_value=[])
    backend.delete_artifact = AsyncMock()
    backend.delete_session_artifacts = AsyncMock(return_value=0)
    backend.initialize = AsyncMock()
    backend.close = AsyncMock()
    backend.is_connected = True
    backend._build_pk = ConversationDynamoDB._build_pk
    return backend


@pytest.fixture
def mock_s3():
    """Mocked S3FileManager."""
    s3 = AsyncMock()
    s3.create_from_bytes = AsyncMock(return_value=None)
    s3.download_file = AsyncMock(return_value=None)
    s3.delete_file = AsyncMock(return_value=True)
    return s3


@pytest.fixture
def overflow(mock_s3):
    return S3OverflowManager(s3_file_manager=mock_s3)


@pytest.fixture
def artifact_store(mock_dynamo, overflow):
    return ArtifactStore(dynamodb=mock_dynamo, s3_overflow=overflow)


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
def chat_storage(mock_redis, mock_dynamo):
    storage = ChatStorage(redis_conversation=mock_redis, dynamodb=mock_dynamo)
    storage._initialized = True
    return storage


# ---------------------------------------------------------------------------
# Integration: Full Conversation Lifecycle
# ---------------------------------------------------------------------------

class TestConversationLifecycle:
    """End-to-end: create thread → add turns → list → load → delete."""

    @pytest.mark.asyncio
    async def test_create_thread(self, chat_storage, mock_dynamo):
        result = await chat_storage.create_conversation(
            user_id="u1", session_id="sess1", agent_id="bot1",
            title="Sales Analysis"
        )
        assert result is not None
        assert result["session_id"] == "sess1"
        assert result["title"] == "Sales Analysis"
        mock_dynamo.put_thread.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_turn_and_fire_dynamodb(self, chat_storage, mock_dynamo):
        turn_id = await chat_storage.save_turn(
            user_id="u1", session_id="sess1", agent_id="bot1",
            user_message="What are Q4 sales?",
            assistant_response="Q4 sales were $2.5M",
        )
        assert turn_id is not None
        # Allow background task to run
        await asyncio.sleep(0.05)
        mock_dynamo.put_turn.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_conversations(self, chat_storage, mock_dynamo):
        mock_dynamo.query_threads.return_value = [
            {
                "PK": "USER#u1#AGENT#bot1",
                "SK": "THREAD#sess1",
                "type": "thread",
                "ttl": 99999,
                "session_id": "sess1",
                "title": "Chat 1",
                "updated_at": "2025-04-16T12:00:00",
            },
            {
                "PK": "USER#u1#AGENT#bot1",
                "SK": "THREAD#sess2",
                "type": "thread",
                "ttl": 99999,
                "session_id": "sess2",
                "title": "Chat 2",
                "updated_at": "2025-04-16T11:00:00",
            },
        ]

        conversations = await chat_storage.list_user_conversations("u1", agent_id="bot1")
        assert len(conversations) == 2
        assert conversations[0]["session_id"] == "sess1"
        # PK/SK/type/ttl should be stripped
        assert "PK" not in conversations[0]
        assert "ttl" not in conversations[0]

    @pytest.mark.asyncio
    async def test_load_conversation_from_dynamodb(self, chat_storage, mock_dynamo, mock_redis):
        mock_redis.get_history.return_value = None
        mock_dynamo.query_turns.return_value = [
            {
                "turn_id": "t001",
                "user_message": "Hello",
                "assistant_response": "Hi there",
                "timestamp": "2025-04-16T12:00:00",
            },
            {
                "turn_id": "t002",
                "user_message": "How are you?",
                "assistant_response": "I'm great!",
                "timestamp": "2025-04-16T12:01:00",
            },
        ]

        messages = await chat_storage.load_conversation("u1", "sess1", agent_id="bot1")
        assert len(messages) == 4  # 2 turns × 2 messages each
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Hi there"

    @pytest.mark.asyncio
    async def test_delete_conversation_cascade(self, chat_storage, mock_dynamo, mock_redis):
        mock_dynamo.delete_thread_cascade.return_value = 5
        mock_dynamo.delete_session_artifacts.return_value = 3

        deleted = await chat_storage.delete_conversation(
            "u1", "sess1", agent_id="bot1"
        )
        assert deleted is True
        mock_dynamo.delete_thread_cascade.assert_called_once()
        mock_dynamo.delete_session_artifacts.assert_called_once()
        mock_redis.delete_history.assert_called_once()


# ---------------------------------------------------------------------------
# Integration: Full Artifact Lifecycle
# ---------------------------------------------------------------------------

class TestArtifactLifecycle:
    """End-to-end: save artifact → list → get → update → delete."""

    @pytest.mark.asyncio
    async def test_save_and_list(self, artifact_store, mock_dynamo):
        now = datetime(2025, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
        artifact = Artifact(
            artifact_id="chart-x1",
            artifact_type=ArtifactType.CHART,
            title="Revenue by Region",
            created_at=now,
            updated_at=now,
            created_by=ArtifactCreator.AGENT,
            definition={"engine": "echarts", "spec": {"xAxis": {}}},
        )

        await artifact_store.save_artifact("u1", "bot1", "sess1", artifact)
        mock_dynamo.put_artifact.assert_called_once()

        # Now list
        mock_dynamo.query_artifacts.return_value = [
            {
                "artifact_id": "chart-x1",
                "artifact_type": "chart",
                "title": "Revenue by Region",
                "created_at": "2025-04-16T12:00:00+00:00",
                "updated_at": "2025-04-16T12:00:00+00:00",
            },
        ]
        summaries = await artifact_store.list_artifacts("u1", "bot1", "sess1")
        assert len(summaries) == 1
        assert isinstance(summaries[0], ArtifactSummary)
        assert summaries[0].id == "chart-x1"
        assert summaries[0].type == ArtifactType.CHART

    @pytest.mark.asyncio
    async def test_get_artifact_inline(self, artifact_store, mock_dynamo):
        mock_dynamo.get_artifact.return_value = {
            "artifact_id": "chart-x1",
            "artifact_type": "chart",
            "title": "Revenue",
            "created_at": "2025-04-16T12:00:00",
            "updated_at": "2025-04-16T12:00:00",
            "definition": {"engine": "echarts"},
            "definition_ref": None,
        }

        result = await artifact_store.get_artifact("u1", "bot1", "sess1", "chart-x1")
        assert result is not None
        assert result.artifact_id == "chart-x1"
        assert result.definition == {"engine": "echarts"}

    @pytest.mark.asyncio
    async def test_update_artifact(self, artifact_store, mock_dynamo):
        mock_dynamo.get_artifact.return_value = {
            "artifact_id": "chart-x1",
            "artifact_type": "chart",
            "title": "Revenue",
            "created_at": "2025-04-16T12:00:00",
            "updated_at": "2025-04-16T12:00:00",
            "definition": {"old": "def"},
            "definition_ref": None,
        }

        await artifact_store.update_artifact(
            "u1", "bot1", "sess1", "chart-x1",
            definition={"new": "definition"},
        )
        # put_artifact should be called with updated data
        mock_dynamo.put_artifact.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_artifact(self, artifact_store, mock_dynamo):
        mock_dynamo.get_artifact.return_value = {
            "artifact_id": "chart-x1",
            "definition_ref": None,
        }

        deleted = await artifact_store.delete_artifact("u1", "bot1", "sess1", "chart-x1")
        assert deleted is True
        mock_dynamo.delete_artifact.assert_called_once()


# ---------------------------------------------------------------------------
# Integration: S3 Overflow
# ---------------------------------------------------------------------------

class TestS3Overflow:
    """End-to-end: large artifact → S3 upload → DynamoDB ref → resolve."""

    @pytest.mark.asyncio
    async def test_large_artifact_offloaded(self, artifact_store, mock_dynamo, mock_s3):
        now = datetime(2025, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
        large_def = {"data": "x" * (250 * 1024)}
        artifact = Artifact(
            artifact_id="big-chart",
            artifact_type=ArtifactType.CHART,
            title="Big Chart",
            created_at=now,
            updated_at=now,
            definition=large_def,
        )

        await artifact_store.save_artifact("u1", "bot1", "sess1", artifact)
        # S3 upload should have been called
        mock_s3.create_from_bytes.assert_called_once()
        # DynamoDB should have definition=None and definition_ref set
        call_kwargs = mock_dynamo.put_artifact.call_args.kwargs
        data = call_kwargs["data"]
        assert data["definition"] is None
        assert data["definition_ref"] is not None

    @pytest.mark.asyncio
    async def test_small_artifact_stays_inline(self, artifact_store, mock_dynamo, mock_s3):
        now = datetime(2025, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
        small_def = {"engine": "echarts", "spec": {}}
        artifact = Artifact(
            artifact_id="small-chart",
            artifact_type=ArtifactType.CHART,
            title="Small Chart",
            created_at=now,
            updated_at=now,
            definition=small_def,
        )

        await artifact_store.save_artifact("u1", "bot1", "sess1", artifact)
        mock_s3.create_from_bytes.assert_not_called()
        call_kwargs = mock_dynamo.put_artifact.call_args.kwargs
        data = call_kwargs["data"]
        assert data["definition"] == small_def
        assert data["definition_ref"] is None


# ---------------------------------------------------------------------------
# Integration: Cascade Delete
# ---------------------------------------------------------------------------

class TestCascadeDelete:
    """Thread delete cleans up both tables."""

    @pytest.mark.asyncio
    async def test_thread_delete_cleans_both_tables(self, chat_storage, mock_dynamo, mock_redis):
        mock_dynamo.delete_thread_cascade.return_value = 10
        mock_dynamo.delete_session_artifacts.return_value = 5

        deleted = await chat_storage.delete_conversation("u1", "sess1", agent_id="bot1")
        assert deleted is True
        mock_dynamo.delete_thread_cascade.assert_called_once_with("u1", "bot1", "sess1")
        mock_dynamo.delete_session_artifacts.assert_called_once_with("u1", "bot1", "sess1")

    @pytest.mark.asyncio
    async def test_artifact_delete_cleans_s3(self, artifact_store, mock_dynamo, mock_s3):
        mock_dynamo.get_artifact.return_value = {
            "artifact_id": "chart-x1",
            "definition_ref": "artifacts/key.json",
        }

        await artifact_store.delete_artifact("u1", "bot1", "sess1", "chart-x1")
        mock_s3.delete_file.assert_called_once_with("artifacts/key.json")
        mock_dynamo.delete_artifact.assert_called_once()


# ---------------------------------------------------------------------------
# Integration: Graceful Degradation
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    """Bot keeps working when DynamoDB is unavailable."""

    @pytest.mark.asyncio
    async def test_no_dynamo_save_turn_still_works(self, mock_redis):
        """ChatStorage with no DynamoDB still saves to Redis."""
        storage = ChatStorage(redis_conversation=mock_redis)
        storage._initialized = True

        turn_id = await storage.save_turn(
            user_id="u1", session_id="sess1", agent_id="bot1",
            user_message="hello", assistant_response="hi",
        )
        assert turn_id is not None
        # Redis should have been called
        mock_redis.add_turn.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_dynamo_load_returns_empty(self):
        """ChatStorage with no DynamoDB and no Redis returns empty."""
        storage = ChatStorage()
        storage._initialized = True
        messages = await storage.load_conversation("u1", "sess1")
        assert messages == []

    @pytest.mark.asyncio
    async def test_no_dynamo_list_returns_empty(self):
        storage = ChatStorage()
        storage._initialized = True
        result = await storage.list_user_conversations("u1")
        assert result == []

    @pytest.mark.asyncio
    async def test_dynamo_error_doesnt_crash_query(self, mock_dynamo, mock_redis):
        from botocore.exceptions import ClientError
        mock_dynamo.query_turns.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "Internal"}}, "Query"
        )
        mock_redis.get_history.return_value = None

        storage = ChatStorage(redis_conversation=mock_redis, dynamodb=mock_dynamo)
        storage._initialized = True

        # Should not raise
        messages = await storage.load_conversation("u1", "sess1", agent_id="bot1")
        assert messages == []


# ---------------------------------------------------------------------------
# Integration: Model Serialization
# ---------------------------------------------------------------------------

class TestModelSerialization:
    """Verify models round-trip correctly through the pipeline."""

    def test_canvas_as_artifact_definition(self):
        """CanvasDefinition can serve as Artifact.definition."""
        now = datetime(2025, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
        canvas = CanvasDefinition(
            tab_id="main",
            title="Analysis Report",
            blocks=[
                CanvasBlock(
                    block_id="b1",
                    block_type=CanvasBlockType.MARKDOWN,
                    content="## Revenue Analysis",
                ),
                CanvasBlock(
                    block_id="b2",
                    block_type=CanvasBlockType.CHART_REF,
                    artifact_ref="chart-x1",
                ),
                CanvasBlock(
                    block_id="b3",
                    block_type=CanvasBlockType.INFOGRAPHIC_REF,
                    artifact_ref="infog-r1",
                ),
            ],
        )
        artifact = Artifact(
            artifact_id="canvas-main",
            artifact_type=ArtifactType.CANVAS,
            title="Main Canvas",
            created_at=now,
            updated_at=now,
            created_by=ArtifactCreator.USER,
            definition=canvas.model_dump(),
        )
        # Round-trip
        data = artifact.model_dump(mode="json")
        restored = Artifact.model_validate(data)
        assert restored.artifact_id == "canvas-main"
        assert restored.definition["tab_id"] == "main"
        assert len(restored.definition["blocks"]) == 3

    def test_thread_metadata_model(self):
        now = datetime(2025, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
        meta = ThreadMetadata(
            session_id="sess1",
            user_id="u1",
            agent_id="bot1",
            title="Analysis Session",
            created_at=now,
            updated_at=now,
            turn_count=15,
            pinned=True,
            tags=["finance", "q4"],
        )
        data = meta.model_dump(mode="json")
        restored = ThreadMetadata.model_validate(data)
        assert restored.turn_count == 15
        assert restored.pinned is True
        assert "finance" in restored.tags
