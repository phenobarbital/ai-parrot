"""Behavioral acceptance tests for scoped store reviews, citations, and lessons."""

import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from parrot.memory.agent_memory.models import MemoryRequestScope
from parrot.memory.agent_memory.runtime import (
    bind_memory_exposure,
    bind_memory_scope,
    reset_memory_exposure,
    reset_memory_scope,
)
from parrot.memory.dynamics.models import ReviewSignal
from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend
from parrot.memory.episodic.models import EpisodeCategory, EpisodeOutcome, EpisodicMemory, MemoryNamespace
from parrot.memory.episodic.store import EpisodicMemoryStore
from parrot.memory.episodic.tools import EpisodicMemoryToolkit


def _namespace(*, tenant_id: str = "tenant-a") -> MemoryNamespace:
    """Build the exact episodic namespace used by runtime scope checks."""
    return MemoryNamespace(
        tenant_id=tenant_id,
        agent_id="agent-a",
        user_id="user-a",
        session_id="session-a",
    )


def _scope() -> MemoryRequestScope:
    """Build a deterministic trusted runtime scope."""
    return MemoryRequestScope(
        tenant_id="tenant-a",
        agent_id="agent-a",
        user_id="user-a",
        session_id="session-a",
        turn_id="turn-a",
        identity_provenance="runtime_derived",
    )


def _episode(
    episode_id: str,
    *,
    namespace: MemoryNamespace,
    outcome: str = "success",
    error_message: str | None = None,
) -> EpisodicMemory:
    """Build a deterministic episode under the supplied namespace."""
    return EpisodicMemory(
        episode_id=episode_id,
        tenant_id=namespace.tenant_id,
        agent_id=namespace.agent_id,
        user_id=namespace.user_id,
        session_id=namespace.session_id,
        room_id=namespace.room_id,
        crew_id=namespace.crew_id,
        model_id=namespace.model_id,
        situation=f"Situation for {episode_id}",
        action_taken="Completed the action",
        outcome=outcome,
        error_message=error_message,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _signal(
    *,
    outcome_revision: int = 0,
    passed_check_ids: tuple[str, ...] = ("check-a",),
    correction_count: int = 0,
) -> ReviewSignal:
    """Build verified coder evidence for a deterministic outcome."""
    return ReviewSignal(
        outcome_id="outcome-a",
        outcome_revision=outcome_revision,
        observed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        scope=_scope(),
        evidence_ref="coder-review/v1/execution-a/task-a/attempt-a",
        source="coder_engine",
        outcome="success",
        first_attempt=correction_count == 0,
        correction_count=correction_count,
        passed_check_ids=passed_check_ids,
    )


@pytest.mark.asyncio
async def test_cite_does_not_reinforce(tmp_path: Path) -> None:
    """Verify citation is runtime-bound and cannot reinforce or cross scope."""
    backend = SQLiteEpisodeBackend(tmp_path / "cite.sqlite")
    await backend.configure()
    namespace = _namespace()
    store = EpisodicMemoryStore(backend, default_ttl_days=0)
    try:
        await backend.store(_episode("episode-a", namespace=namespace))
        await backend.store(_episode("episode-b", namespace=namespace))
        await backend.store(_episode("episode-cross", namespace=_namespace(tenant_id="tenant-b")))
        toolkit = EpisodicMemoryToolkit(store=store, namespace=namespace)

        assert "no runtime memory exposure" in await toolkit.cite_memory(["episode-a"])
        scope_token = bind_memory_scope(_scope())
        exposure_token = bind_memory_exposure("exposure-a")
        try:
            acknowledgement = await toolkit.cite_memory(["episode-a"])
        finally:
            reset_memory_exposure(exposure_token)
            reset_memory_scope(scope_token)
        assert acknowledgement == "Cited 1 delivered episodic memories."

        assert backend._db is not None
        review_cursor = await backend._db.execute("SELECT COUNT(*) FROM reviews")
        state_cursor = await backend._db.execute("SELECT COUNT(*) FROM memory_state")
        assert (await review_cursor.fetchone())[0] == 0
        assert (await state_cursor.fetchone())[0] == 0

        with pytest.raises(ValueError, match="references are unavailable"):
            await store.cite(["episode-cross"], namespace=namespace, exposure_id="exposure-cross")
        with pytest.raises(ValueError, match="references are unavailable"):
            await store.cite(["missing"], namespace=namespace, exposure_id="exposure-missing")
        with pytest.raises(ValueError, match="scope or delivered exposure is unavailable"):
            await store.review(["episode-b"], _signal(), namespace=namespace, exposure_id="exposure-a")
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_review_admission_and_idempotency(tmp_path: Path) -> None:
    """Verify cited reviews apply once and revisions/conflicts retain frozen semantics."""
    backend = SQLiteEpisodeBackend(tmp_path / "reviews.sqlite")
    await backend.configure()
    namespace = _namespace()
    store = EpisodicMemoryStore(backend, default_ttl_days=0)
    try:
        await backend.store(_episode("episode-a", namespace=namespace))
        await store.cite(["episode-a"], namespace=namespace, exposure_id="exposure-a")

        first = await store.review(["episode-a"], _signal(), namespace=namespace, exposure_id="exposure-a")
        duplicate = await store.review(["episode-a"], _signal(), namespace=namespace, exposure_id="exposure-a")
        conflict = await store.review(
            ["episode-a"],
            _signal(passed_check_ids=("check-b",)),
            namespace=namespace,
            exposure_id="exposure-a",
        )
        revised = await store.review(
            ["episode-a"],
            _signal(outcome_revision=1, correction_count=1),
            namespace=namespace,
            exposure_id="exposure-a",
        )

        assert [receipt.status for receipt in first] == ["applied"]
        assert [receipt.status for receipt in duplicate] == ["duplicate"]
        assert [receipt.status for receipt in conflict] == ["conflict"]
        assert [receipt.status for receipt in revised] == ["applied"]
        assert revised[0].apply_revision == 2

        assert backend._db is not None
        review_cursor = await backend._db.execute("SELECT COUNT(*) FROM reviews")
        state_cursor = await backend._db.execute("SELECT apply_revision FROM memory_state")
        assert (await review_cursor.fetchone())[0] == 2
        assert (await state_cursor.fetchone())[0] == 2
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_lesson_text_persisted_before_ack(tmp_path: Path) -> None:
    """Verify an acknowledged explicit lesson survives a real-store reopen."""
    path = tmp_path / "lessons.sqlite"
    namespace = _namespace()
    backend = SQLiteEpisodeBackend(path)
    await backend.configure()
    try:
        toolkit = EpisodicMemoryToolkit(
            store=EpisodicMemoryStore(backend, default_ttl_days=0),
            namespace=namespace,
        )
        acknowledgement = await toolkit.record_lesson(
            situation="A deploy failed after skipping validation",
            lesson="Run the scoped validation before deployment",
            category="error_recovery",
            importance=8,
        )
        assert "Lesson recorded" in acknowledgement
    finally:
        await backend.close()

    reopened = SQLiteEpisodeBackend(path)
    await reopened.configure()
    try:
        episodes = await reopened.get_recent(namespace.build_filter(), limit=1)
        assert len(episodes) == 1
        assert episodes[0].lesson_learned == "Run the scoped validation before deployment"
        assert episodes[0].reflection == "Agent explicitly recorded: Run the scoped validation before deployment"
        assert episodes[0].metadata == {}
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_store_list_reviews_delegates_and_fails_visibly(tmp_path: Path) -> None:
    """The store forwards review listing and rejects backends without that capability."""
    namespace = _namespace()
    backend = SQLiteEpisodeBackend(tmp_path / "delegation.sqlite")
    await backend.configure()
    try:
        store = EpisodicMemoryStore(backend, default_ttl_days=0)
        await backend.store(_episode("episode-a", namespace=namespace, error_message="the recorded error"))
        await store.cite(["episode-a"], namespace=namespace, exposure_id="exposure-a")
        assert (await store.review(["episode-a"], _signal(), namespace=namespace, exposure_id="exposure-a"))[
            0
        ].status == "applied"
        rows = await store.list_reviews(namespace)
        assert len(rows) == 1
        assert rows[0]["command"]["ref"]["memory_id"] == "episode-a"
        record = rows[0]["record"]
        assert record["grade"] == 3
        assert record["before"] == {
            "difficulty": None,
            "stability": None,
            "reviewed_at": None,
            "review_count": 0,
            "apply_revision": 0,
            "status": "uninitialized",
            "parameter_id": None,
        }
        assert record["after"]["status"] == "reviewed"
        assert record["after"]["review_count"] == 1
        assert record["after"]["apply_revision"] == 1
        assert record["after"]["parameter_id"] == "episodic-neutral-v1"
        assert math.isfinite(record["after"]["difficulty"])
        assert math.isfinite(record["after"]["stability"])
        assert record["parameter_id"] == "episodic-neutral-v1"
        assert record["memory_error_signature"] == "the recorded error"
    finally:
        await backend.close()

    with pytest.raises(RuntimeError, match="has no list_reviews capability"):
        await EpisodicMemoryStore(object()).list_reviews(namespace)


class _PartialCache:
    """Cache double whose recent window is shorter than the requested scope."""

    def __init__(self, episodes: list[EpisodicMemory]) -> None:
        self._episodes = episodes

    async def get_recent(self, namespace: MemoryNamespace, limit: int = 10) -> list[EpisodicMemory]:
        return self._episodes[:limit]


@pytest.mark.asyncio
async def test_partial_recent_cache_is_not_treated_as_complete(tmp_path: Path) -> None:
    """A warm cache that holds fewer episodes than the scope must not hide the rest from category filters."""
    namespace = MemoryNamespace(tenant_id="tenant-a", agent_id="agent-a", user_id="user-a")
    backend = SQLiteEpisodeBackend(tmp_path / "episodes.sqlite")
    await backend.configure()
    try:
        store = EpisodicMemoryStore(backend, default_ttl_days=0)
        for index in range(4):
            await store.record_episode(
                namespace=namespace,
                situation=f"preference {index}",
                action_taken="noted",
                outcome=EpisodeOutcome.SUCCESS,
                category=EpisodeCategory.USER_PREFERENCE,
                generate_reflection=False,
            )
        newest = (await backend.get_recent(namespace.build_filter(), limit=1))[0]
        store._cache = _PartialCache([newest])  # type: ignore[assignment]

        preferences = await store.get_user_preferences(namespace, limit=10)

        assert len(preferences) == 4
    finally:
        await backend.close()
