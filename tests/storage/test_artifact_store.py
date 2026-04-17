"""Unit tests for ArtifactStore (TASK-720).

All tests use mocked ConversationDynamoDB and S3OverflowManager.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock

from parrot.storage.artifacts import ArtifactStore
from parrot.storage.models import (
    Artifact,
    ArtifactType,
    ArtifactCreator,
    ArtifactSummary,
)


@pytest.fixture
def mock_dynamo():
    db = AsyncMock()
    db.put_artifact = AsyncMock()
    db.get_artifact = AsyncMock(return_value=None)
    db.query_artifacts = AsyncMock(return_value=[])
    db.delete_artifact = AsyncMock()
    return db


@pytest.fixture
def mock_overflow():
    overflow = AsyncMock()
    # Default: inline, no S3
    overflow.maybe_offload.return_value = ({"engine": "echarts"}, None)
    overflow.resolve.return_value = {"engine": "echarts"}
    overflow.delete = AsyncMock()
    return overflow


@pytest.fixture
def store(mock_dynamo, mock_overflow):
    return ArtifactStore(dynamodb=mock_dynamo, s3_overflow=mock_overflow)


def _sample_artifact(**overrides) -> Artifact:
    """Build a sample Artifact for tests."""
    now = datetime(2025, 4, 16, 12, 0, 0)
    defaults = dict(
        artifact_id="chart-x1",
        artifact_type=ArtifactType.CHART,
        title="Test Chart",
        created_at=now,
        updated_at=now,
        definition={"engine": "echarts", "spec": {}},
    )
    defaults.update(overrides)
    return Artifact(**defaults)


class TestSaveArtifact:
    """Tests for save_artifact method."""

    @pytest.mark.asyncio
    async def test_calls_overflow_and_dynamo(self, store, mock_dynamo, mock_overflow):
        artifact = _sample_artifact()
        await store.save_artifact("u1", "agent1", "sess1", artifact)
        mock_overflow.maybe_offload.assert_called_once()
        mock_dynamo.put_artifact.assert_called_once()

    @pytest.mark.asyncio
    async def test_inline_definition_stored(self, store, mock_dynamo, mock_overflow):
        mock_overflow.maybe_offload.return_value = ({"engine": "echarts"}, None)
        artifact = _sample_artifact()
        await store.save_artifact("u1", "agent1", "sess1", artifact)

        call_kwargs = mock_dynamo.put_artifact.call_args.kwargs
        data = call_kwargs["data"]
        assert data["definition"] == {"engine": "echarts"}
        assert data["definition_ref"] is None

    @pytest.mark.asyncio
    async def test_s3_offloaded_definition(self, store, mock_dynamo, mock_overflow):
        mock_overflow.maybe_offload.return_value = (None, "artifacts/key.json")
        artifact = _sample_artifact()
        await store.save_artifact("u1", "agent1", "sess1", artifact)

        call_kwargs = mock_dynamo.put_artifact.call_args.kwargs
        data = call_kwargs["data"]
        assert data["definition"] is None
        assert data["definition_ref"] == "artifacts/key.json"

    @pytest.mark.asyncio
    async def test_artifact_id_passed_to_dynamo(self, store, mock_dynamo, mock_overflow):
        artifact = _sample_artifact(artifact_id="infog-r1")
        await store.save_artifact("u1", "agent1", "sess1", artifact)

        call_kwargs = mock_dynamo.put_artifact.call_args.kwargs
        assert call_kwargs["artifact_id"] == "infog-r1"

    @pytest.mark.asyncio
    async def test_none_definition_skips_overflow(self, store, mock_dynamo, mock_overflow):
        artifact = _sample_artifact(
            definition=None,
            definition_ref="s3://bucket/key.json",
        )
        await store.save_artifact("u1", "agent1", "sess1", artifact)
        mock_overflow.maybe_offload.assert_not_called()


class TestGetArtifact:
    """Tests for get_artifact method."""

    @pytest.mark.asyncio
    async def test_returns_none_if_not_found(self, store, mock_dynamo):
        mock_dynamo.get_artifact.return_value = None
        result = await store.get_artifact("u1", "agent1", "sess1", "nope")
        assert result is None

    @pytest.mark.asyncio
    async def test_resolves_s3_ref(self, store, mock_dynamo, mock_overflow):
        mock_dynamo.get_artifact.return_value = {
            "artifact_id": "infog-1",
            "artifact_type": "infographic",
            "title": "Big Infographic",
            "created_at": "2025-04-16T12:00:00",
            "updated_at": "2025-04-16T12:00:00",
            "definition": None,
            "definition_ref": "s3://bucket/key.json",
        }
        mock_overflow.resolve.return_value = {"blocks": []}

        result = await store.get_artifact("u1", "agent1", "sess1", "infog-1")
        assert result is not None
        assert result.artifact_id == "infog-1"
        assert result.definition == {"blocks": []}
        mock_overflow.resolve.assert_called_once_with(None, "s3://bucket/key.json")

    @pytest.mark.asyncio
    async def test_inline_definition(self, store, mock_dynamo, mock_overflow):
        inline_def = {"engine": "echarts", "spec": {}}
        mock_dynamo.get_artifact.return_value = {
            "artifact_id": "chart-1",
            "artifact_type": "chart",
            "title": "Chart",
            "created_at": "2025-04-16T12:00:00",
            "updated_at": "2025-04-16T12:00:00",
            "definition": inline_def,
            "definition_ref": None,
        }
        mock_overflow.resolve.return_value = inline_def

        result = await store.get_artifact("u1", "agent1", "sess1", "chart-1")
        assert result is not None
        assert result.definition == inline_def


class TestListArtifacts:
    """Tests for list_artifacts method."""

    @pytest.mark.asyncio
    async def test_returns_summaries(self, store, mock_dynamo):
        mock_dynamo.query_artifacts.return_value = [
            {
                "artifact_id": "chart-1",
                "artifact_type": "chart",
                "title": "Chart 1",
                "created_at": "2025-04-16T00:00:00",
                "updated_at": "2025-04-16T00:00:00",
            },
            {
                "artifact_id": "infog-1",
                "artifact_type": "infographic",
                "title": "Infographic 1",
                "created_at": "2025-04-16T01:00:00",
                "updated_at": "2025-04-16T01:00:00",
            },
        ]

        results = await store.list_artifacts("u1", "agent1", "sess1")
        assert len(results) == 2
        assert all(isinstance(r, ArtifactSummary) for r in results)
        assert results[0].id == "chart-1"
        assert results[0].type == ArtifactType.CHART
        assert results[1].id == "infog-1"

    @pytest.mark.asyncio
    async def test_empty_session_returns_empty(self, store, mock_dynamo):
        mock_dynamo.query_artifacts.return_value = []
        results = await store.list_artifacts("u1", "agent1", "sess1")
        assert results == []

    @pytest.mark.asyncio
    async def test_bad_item_skipped(self, store, mock_dynamo):
        """Malformed items should be skipped, not crash."""
        mock_dynamo.query_artifacts.return_value = [
            {"bad": "data"},  # Missing required fields
            {
                "artifact_id": "good-1",
                "artifact_type": "chart",
                "title": "Good",
                "created_at": "2025-04-16T00:00:00",
            },
        ]
        results = await store.list_artifacts("u1", "agent1", "sess1")
        assert len(results) == 1
        assert results[0].id == "good-1"


class TestUpdateArtifact:
    """Tests for update_artifact method."""

    @pytest.mark.asyncio
    async def test_deletes_old_s3_ref(self, store, mock_dynamo, mock_overflow):
        mock_dynamo.get_artifact.return_value = {
            "artifact_id": "chart-1",
            "artifact_type": "chart",
            "title": "Chart",
            "created_at": "2025-04-16T00:00:00",
            "updated_at": "2025-04-16T00:00:00",
            "definition": None,
            "definition_ref": "old/key.json",
        }
        mock_overflow.maybe_offload.return_value = ({"new": "def"}, None)

        await store.update_artifact("u1", "agent1", "sess1", "chart-1", {"new": "def"})
        mock_overflow.delete.assert_called_once_with("old/key.json")

    @pytest.mark.asyncio
    async def test_no_old_ref_no_delete(self, store, mock_dynamo, mock_overflow):
        mock_dynamo.get_artifact.return_value = {
            "artifact_id": "chart-1",
            "artifact_type": "chart",
            "title": "Chart",
            "created_at": "2025-04-16T00:00:00",
            "updated_at": "2025-04-16T00:00:00",
            "definition": {"old": "def"},
            "definition_ref": None,
        }
        mock_overflow.maybe_offload.return_value = ({"new": "def"}, None)

        await store.update_artifact("u1", "agent1", "sess1", "chart-1", {"new": "def"})
        mock_overflow.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_calls_put_artifact(self, store, mock_dynamo, mock_overflow):
        mock_dynamo.get_artifact.return_value = None
        mock_overflow.maybe_offload.return_value = ({"new": "def"}, None)

        await store.update_artifact("u1", "agent1", "sess1", "chart-1", {"new": "def"})
        mock_dynamo.put_artifact.assert_called_once()


class TestDeleteArtifact:
    """Tests for delete_artifact method."""

    @pytest.mark.asyncio
    async def test_deletes_s3_and_dynamo(self, store, mock_dynamo, mock_overflow):
        mock_dynamo.get_artifact.return_value = {
            "artifact_id": "chart-1",
            "definition_ref": "artifacts/key.json",
        }

        result = await store.delete_artifact("u1", "agent1", "sess1", "chart-1")
        assert result is True
        mock_overflow.delete.assert_called_once_with("artifacts/key.json")
        mock_dynamo.delete_artifact.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_s3_ref_only_dynamo(self, store, mock_dynamo, mock_overflow):
        mock_dynamo.get_artifact.return_value = {
            "artifact_id": "chart-1",
            "definition_ref": None,
        }

        result = await store.delete_artifact("u1", "agent1", "sess1", "chart-1")
        assert result is True
        mock_overflow.delete.assert_not_called()
        mock_dynamo.delete_artifact.assert_called_once()

    @pytest.mark.asyncio
    async def test_not_found_returns_false(self, store, mock_dynamo):
        mock_dynamo.get_artifact.return_value = None
        result = await store.delete_artifact("u1", "agent1", "sess1", "nope")
        assert result is False
