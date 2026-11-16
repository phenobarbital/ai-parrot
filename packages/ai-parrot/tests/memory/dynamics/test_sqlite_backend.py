"""Behavioral acceptance tests for SQLite episodic persistence and measured vector ceiling."""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend
from parrot.memory.dynamics.models import ReviewCommand
from parrot.memory.episodic.models import EpisodicMemory, MemoryNamespace

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


def _review_command(
    namespace: MemoryNamespace,
    *,
    episode_id: str,
    outcome_id: str,
    expected_revision: int = 0,
) -> ReviewCommand:
    """Build a validated command for the fixed review-listing episode."""
    return ReviewCommand.model_validate(
        {
            "ref": {
                "namespace": namespace.model_dump(mode="json"),
                "kind": "episode",
                "memory_id": episode_id,
                "content_version": "v1",
            },
            "signal": {
                "outcome_id": outcome_id,
                "outcome_revision": 0,
                "observed_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
                "scope": {
                    **namespace.model_dump(mode="json"),
                    "turn_id": "turn-a",
                    "identity_provenance": "runtime_derived",
                },
                "evidence_ref": f"coder-review/v1/execution/task/{outcome_id}",
                "source": "coder_engine",
                "outcome": "success",
                "first_attempt": True,
                "correction_count": 0,
                "passed_check_ids": ("sqlite-listing",),
            },
            "exposure_id": f"exposure-{outcome_id}",
            "expected_revision": expected_revision,
        }
    )


@pytest.mark.asyncio
async def test_list_reviews_scope_before_limit_and_deterministic_order(tmp_path) -> None:
    """Review scope predicates run before the requested limit and preserve total order."""
    backend = SQLiteEpisodeBackend(tmp_path / "reviews.sqlite")
    await backend.configure()
    scoped = MemoryNamespace(tenant_id="tenant-a", agent_id="agent-a", user_id="user-a", session_id="session-a")
    other = MemoryNamespace(tenant_id="tenant-b", agent_id="agent-a", user_id="user-a", session_id="session-a")
    try:
        await backend.store(
            _episode(
                10,
                episode_id="other-episode",
                tenant_id=other.tenant_id,
                user_id=other.user_id,
                session_id=other.session_id,
            )
        )
        assert (
            await backend.apply_review(_review_command(other, episode_id="other-episode", outcome_id="other"))
        ).status == "applied"
        await backend.store(
            _episode(
                11,
                episode_id="review-episode",
                tenant_id=scoped.tenant_id,
                user_id=scoped.user_id,
                session_id=scoped.session_id,
            )
        )
        assert (
            await backend.apply_review(_review_command(scoped, episode_id="review-episode", outcome_id="first"))
        ).status == "applied"
        assert (
            await backend.apply_review(
                _review_command(scoped, episode_id="review-episode", outcome_id="second", expected_revision=1)
            )
        ).status == "applied"

        limited = await backend.list_reviews(scoped, limit=1)
        listed = await backend.list_reviews(scoped)
        assert [row["command"]["signal"]["outcome_id"] for row in limited] == ["first"]
        assert [row["command"]["signal"]["outcome_id"] for row in listed] == ["first", "second"]
        assert all(
            set(row)
            == {"dedupe_key", "outcome_id", "outcome_revision", "ref_key", "apply_revision", "recorded_at", "command"}
            for row in listed
        )
        with pytest.raises(ValueError, match="limit must be positive"):
            await backend.list_reviews(scoped, limit=0)
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_list_reviews_closed_backend_fails_visibly(tmp_path) -> None:
    """The optional review read API must not turn an unopened backend into an empty result."""
    backend = SQLiteEpisodeBackend(tmp_path / "closed.sqlite")
    namespace = MemoryNamespace(tenant_id="tenant-a", agent_id="agent-a")
    with pytest.raises(RuntimeError, match="not configured"):
        await backend.list_reviews(namespace)
