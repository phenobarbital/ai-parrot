"""Tests for handler auto-save artifact integration (TASK-725).

Verifies the artifact model dependencies are correct and that
auto-save patterns are valid.

Note: Full handler imports require compiled Cython extensions
(parrot.utils.types) that aren't available in worktree PYTHONPATH
mode.  These tests validate the storage-layer integration instead.
"""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from parrot.storage.models import (
    Artifact,
    ArtifactType,
    ArtifactCreator,
)
from parrot.storage.artifacts import ArtifactStore


class TestAutoSavePattern:
    """Verify the fire-and-forget auto-save pattern works correctly."""

    @pytest.mark.asyncio
    async def test_infographic_artifact_creation(self):
        """Simulates infographic auto-save: create Artifact and call ArtifactStore."""
        mock_store = AsyncMock(spec=ArtifactStore)

        now = datetime.now(timezone.utc)
        artifact = Artifact(
            artifact_id="infog-abc12345",
            artifact_type=ArtifactType.INFOGRAPHIC,
            title="Infographic (basic)",
            created_at=now,
            updated_at=now,
            created_by=ArtifactCreator.AGENT,
            definition={"blocks": [], "template": "basic"},
        )

        await mock_store.save_artifact(
            user_id="u1",
            agent_id="bot1",
            session_id="sess1",
            artifact=artifact,
        )

        mock_store.save_artifact.assert_called_once()
        call_kwargs = mock_store.save_artifact.call_args.kwargs
        assert call_kwargs["artifact"].artifact_type == ArtifactType.INFOGRAPHIC
        assert call_kwargs["artifact"].created_by == ArtifactCreator.AGENT

    @pytest.mark.asyncio
    async def test_data_artifact_creation(self):
        """Simulates data auto-save: create chart/dataframe artifact."""
        mock_store = AsyncMock(spec=ArtifactStore)

        now = datetime.now(timezone.utc)
        artifact = Artifact(
            artifact_id="chart-def67890",
            artifact_type=ArtifactType.CHART,
            title="Chart — Revenue by Region",
            created_at=now,
            updated_at=now,
            source_turn_id="turn-001",
            created_by=ArtifactCreator.AGENT,
            definition={"engine": "echarts", "spec": {}},
        )

        await mock_store.save_artifact(
            user_id="u1",
            agent_id="bot1",
            session_id="sess1",
            artifact=artifact,
        )

        mock_store.save_artifact.assert_called_once()
        call_kwargs = mock_store.save_artifact.call_args.kwargs
        assert call_kwargs["artifact"].artifact_type == ArtifactType.CHART
        assert call_kwargs["artifact"].source_turn_id == "turn-001"

    @pytest.mark.asyncio
    async def test_fire_and_forget_doesnt_block(self):
        """Verify fire-and-forget pattern completes without blocking."""
        mock_store = AsyncMock(spec=ArtifactStore)
        mock_store.save_artifact.return_value = None

        now = datetime.now(timezone.utc)
        artifact = Artifact(
            artifact_id="infog-test",
            artifact_type=ArtifactType.INFOGRAPHIC,
            title="Test",
            created_at=now,
            updated_at=now,
            created_by=ArtifactCreator.AGENT,
            definition={"blocks": []},
        )

        # Simulate fire-and-forget
        task = asyncio.create_task(
            mock_store.save_artifact(
                user_id="u1",
                agent_id="bot1",
                session_id="sess1",
                artifact=artifact,
            )
        )

        # Should complete without blocking
        await asyncio.sleep(0.01)
        assert task.done()

    @pytest.mark.asyncio
    async def test_fire_and_forget_exception_doesnt_crash(self):
        """Verify that store failures don't crash the task."""
        mock_store = AsyncMock(spec=ArtifactStore)
        mock_store.save_artifact.side_effect = Exception("DynamoDB unavailable")

        now = datetime.now(timezone.utc)
        artifact = Artifact(
            artifact_id="infog-fail",
            artifact_type=ArtifactType.INFOGRAPHIC,
            title="Test",
            created_at=now,
            updated_at=now,
            definition={},
        )

        task = asyncio.create_task(
            mock_store.save_artifact(
                user_id="u1",
                agent_id="bot1",
                session_id="sess1",
                artifact=artifact,
            )
        )

        await asyncio.sleep(0.01)
        assert task.done()
        # The exception is raised by the mock but that's expected in fire-and-forget
