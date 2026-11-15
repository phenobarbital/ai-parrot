"""Behavioral acceptance tests for SQLite episodic persistence and measured vector ceiling."""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend
from parrot.memory.episodic.models import EpisodicMemory


def _episode(index: int, **overrides: object) -> EpisodicMemory:
    """Create a deterministic episode suitable for an isolated SQLite store."""
    data: dict[str, object] = {
        "episode_id": f"episode-{index}",
        "agent_id": "agent-a",
        "tenant_id": "tenant-a",
        "situation": f"Situation {index}",
        "action_taken": f"Action {index}",
        "outcome": "success",
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index),
        "embedding": [1.0, 0.0],
    }
    data.update(overrides)
    return EpisodicMemory(**data)


@pytest.mark.asyncio
async def test_persist_reopen_and_failed_write(tmp_path) -> None:
    """Verify committed writes survive reopen while serialization failures roll back."""
    path = tmp_path / "episodes.sqlite"
    backend = SQLiteEpisodeBackend(path)
    await backend.configure()
    episode = _episode(1)
    assert await backend.store(episode) == episode.episode_id
    assert backend._db is not None
    await backend._db.execute(
        "CREATE TRIGGER reject_episode BEFORE INSERT ON episodes "
        "WHEN NEW.episode_id = 'episode-2' BEGIN SELECT RAISE(ABORT, 'forced write failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="forced write failure"):
        await backend.store(_episode(2))
    assert await backend.count({"tenant_id": "tenant-a", "agent_id": "agent-a"}) == 1
    await backend.close()

    reopened = SQLiteEpisodeBackend(path)
    await reopened.configure()
    try:
        records = await reopened.get_recent({"tenant_id": "tenant-a", "agent_id": "agent-a"})
        assert [record.episode_id for record in records] == [episode.episode_id]
        assert records[0].embedding == pytest.approx([1.0, 0.0])
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_scope_before_top_k(tmp_path) -> None:
    """Verify scope predicates are applied before vector and recent limits."""
    backend = SQLiteEpisodeBackend(tmp_path / "episodes.sqlite")
    await backend.configure()
    try:
        for index in range(3):
            await backend.store(_episode(index, tenant_id="other-tenant"))
        scoped = _episode(10, model_id="model-a")
        await backend.store(scoped)

        results = await backend.search_similar(
            [1.0, 0.0],
            {"tenant_id": "tenant-a", "agent_id": "agent-a", "model_id": "model-a"},
            top_k=1,
        )
        recent = await backend.get_recent(
            {"tenant_id": "tenant-a", "agent_id": "agent-a", "model_id": "model-a"}, limit=1
        )

        assert [result.episode_id for result in results] == [scoped.episode_id]
        assert [record.episode_id for record in recent] == [scoped.episode_id]
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_measured_ceiling_reports_degradation(tmp_path) -> None:
    """Verify over-ceiling vector search reports degradation without lexical substitution."""
    backend = SQLiteEpisodeBackend(tmp_path / "episodes.sqlite", vector_ceiling=2)
    await backend.configure()
    try:
        for index in range(3):
            await backend.store(_episode(index))

        status = await backend.vector_status({"tenant_id": "tenant-a", "agent_id": "agent-a"})
        results = await backend.search_similar([1.0, 0.0], {"tenant_id": "tenant-a", "agent_id": "agent-a"}, top_k=5)

        assert status == {"status": "degraded", "candidate_count": 3, "vector_ceiling": 2}
        assert [result.episode_id for result in results] == ["episode-2", "episode-1"]
    finally:
        await backend.close()
