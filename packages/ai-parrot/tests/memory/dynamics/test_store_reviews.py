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
async def test_cross_session_reviews_share_original_state_and_replay(tmp_path: Path) -> None:
    """Visible old-session and agent-level refs share durable state across requesting sessions."""
    path = tmp_path / "cross-session.sqlite"
    backend = SQLiteEpisodeBackend(path)
    await backend.configure()
    requester = _namespace()
    original = requester.model_copy(update={"session_id": "earlier"})
    agent = requester.model_copy(update={"user_id": None, "session_id": None})
    store = EpisodicMemoryStore(backend, default_ttl_days=0)
    ids = ["old-session", "agent-lesson"]
    try:
        await backend.store(_episode(ids[0], namespace=original))
        await backend.store(_episode(ids[1], namespace=agent))
        citation = await store.cite(ids, namespace=requester, exposure_id="first")
        assert [ref.namespace for ref in citation.refs] == [original, agent]
        first = await store.review(ids, _signal(), namespace=requester, exposure_id="first")
        assert [receipt.status for receipt in first] == ["applied", "applied"]
        second_request = requester.model_copy(update={"session_id": "later"})
        second_signal = _signal().model_copy(update={"scope": _scope().model_copy(update={"session_id": "later"})})
        second_citation = await store.cite(ids, namespace=second_request, exposure_id="second")
        assert second_citation.refs == citation.refs
        second = await store.review(ids, second_signal, namespace=second_request, exposure_id="second")
        assert [receipt.status for receipt in second] == ["applied", "applied"]
        assert [receipt.apply_revision for receipt in second] == [2, 2]
        assert [receipt.dedupe_key for receipt in first] != [receipt.dedupe_key for receipt in second]
        assert backend._db is not None
        assert (await (await backend._db.execute("SELECT COUNT(*) FROM memory_state")).fetchone())[0] == 2
        records = await backend.list_reviews(agent)
        assert {row["command"]["signal"]["scope"]["session_id"] for row in records} == {"session-a", "later"}
    finally:
        await backend.close()
    reopened = SQLiteEpisodeBackend(path)
    await reopened.configure()
    try:
        replay = await EpisodicMemoryStore(reopened).review(
            ids, second_signal, namespace=second_request, exposure_id="second"
        )
        assert [receipt.status for receipt in replay] == ["duplicate", "duplicate"]
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_cross_scope_resolution_rejects_hidden_and_altered_refs(tmp_path: Path) -> None:
    """Visibility and stored full refs are checked even when the canonical key matches."""
    from parrot.memory.dynamics.models import MemoryCitation

    backend = SQLiteEpisodeBackend(tmp_path / "ref-admission.sqlite")
    await backend.configure()
    store = EpisodicMemoryStore(backend)
    request = _namespace()
    try:
        for name, update in [
            ("other-user", {"user_id": "other"}),
            ("anonymous", {"user_id": None, "session_id": "private"}),
            ("other-agent", {"agent_id": "other"}),
        ]:
            await backend.store(_episode(name, namespace=request.model_copy(update=update)))
            with pytest.raises(ValueError, match="references are unavailable"):
                await store.cite([name], namespace=request, exposure_id=name)
        await backend.store(_episode("visible", namespace=request.model_copy(update={"model_id": "actual"})))
        citation = await store.cite(["visible"], namespace=request, exposure_id="valid")
        forged = citation.refs[0].model_copy(
            update={"namespace": citation.refs[0].namespace.model_copy(update={"model_id": "forged"})}
        )
        await backend.merge_citation(MemoryCitation(exposure_id="forged", refs=(forged,)))
        with pytest.raises(ValueError, match="scope or delivered exposure"):
            await store.review(["visible"], _signal(), namespace=request, exposure_id="forged")
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


@pytest.mark.asyncio
async def test_review_retry_through_new_store_instance_is_duplicate(tmp_path: Path) -> None:
    """Verify a restart retry of a review committed at a non-zero revision is a duplicate, not a conflict."""
    path = tmp_path / "restart.sqlite"
    namespace = _namespace()
    revised_signal = _signal(outcome_revision=1, correction_count=1)

    first_backend = SQLiteEpisodeBackend(path)
    await first_backend.configure()
    try:
        first_store = EpisodicMemoryStore(first_backend, default_ttl_days=0)
        await first_backend.store(_episode("episode-a", namespace=namespace))
        await first_store.cite(["episode-a"], namespace=namespace, exposure_id="exposure-a")
        initial = await first_store.review(["episode-a"], _signal(), namespace=namespace, exposure_id="exposure-a")
        revised = await first_store.review(["episode-a"], revised_signal, namespace=namespace, exposure_id="exposure-a")
        assert [receipt.status for receipt in initial] == ["applied"]
        assert [receipt.status for receipt in revised] == ["applied"]
        assert revised[0].apply_revision == 2
    finally:
        await first_backend.close()

    second_backend = SQLiteEpisodeBackend(path)
    await second_backend.configure()
    try:
        second_store = EpisodicMemoryStore(second_backend, default_ttl_days=0)
        retried = await second_store.review(
            ["episode-a"], revised_signal, namespace=namespace, exposure_id="exposure-a"
        )
        retried_initial = await second_store.review(
            ["episode-a"], _signal(), namespace=namespace, exposure_id="exposure-a"
        )
        conflict = await second_store.review(
            ["episode-a"],
            _signal(outcome_revision=1, correction_count=1, passed_check_ids=("check-b",)),
            namespace=namespace,
            exposure_id="exposure-a",
        )

        assert [receipt.status for receipt in retried] == ["duplicate"]
        assert retried[0].apply_revision == 2
        assert [receipt.status for receipt in retried_initial] == ["duplicate"]
        assert [receipt.status for receipt in conflict] == ["conflict"]

        assert second_backend._db is not None
        review_cursor = await second_backend._db.execute("SELECT COUNT(*) FROM reviews")
        state_cursor = await second_backend._db.execute("SELECT apply_revision FROM memory_state")
        assert (await review_cursor.fetchone())[0] == 2
        assert (await state_cursor.fetchone())[0] == 2
    finally:
        await second_backend.close()


@pytest.mark.asyncio
async def test_citation_is_shared_across_store_instances(tmp_path: Path) -> None:
    """Verify an exposure cited by one store instance admits a review through another over one database."""
    path = tmp_path / "citations.sqlite"
    namespace = _namespace()
    citing_backend = SQLiteEpisodeBackend(path)
    reviewing_backend = SQLiteEpisodeBackend(path)
    await citing_backend.configure()
    await reviewing_backend.configure()
    try:
        citing_store = EpisodicMemoryStore(citing_backend, default_ttl_days=0)
        reviewing_store = EpisodicMemoryStore(reviewing_backend, default_ttl_days=0)
        await citing_backend.store(_episode("episode-a", namespace=namespace))
        await citing_backend.store(_episode("episode-b", namespace=namespace))
        await citing_backend.store(_episode("episode-c", namespace=namespace))

        await citing_store.cite(["episode-a"], namespace=namespace, exposure_id="exposure-a")
        await reviewing_store.cite(["episode-b"], namespace=namespace, exposure_id="exposure-a")

        receipts = await reviewing_store.review(
            ["episode-a", "episode-b"], _signal(), namespace=namespace, exposure_id="exposure-a"
        )
        assert [receipt.status for receipt in receipts] == ["applied", "applied"]

        with pytest.raises(ValueError, match="scope or delivered exposure is unavailable"):
            await citing_store.review(["episode-c"], _signal(), namespace=namespace, exposure_id="exposure-a")
        with pytest.raises(ValueError, match="scope or delivered exposure is unavailable"):
            await reviewing_store.review(["episode-a"], _signal(), namespace=namespace, exposure_id="exposure-other")
    finally:
        await citing_backend.close()
        await reviewing_backend.close()


@pytest.mark.asyncio
async def test_durable_citation_rejects_other_namespace_and_prunes_expired(tmp_path: Path) -> None:
    """Verify a durable exposure cannot change namespace and stale citations are pruned on write."""
    backend = SQLiteEpisodeBackend(tmp_path / "citation-scope.sqlite")
    await backend.configure()
    namespace = _namespace()
    other_namespace = _namespace(tenant_id="tenant-b")
    store = EpisodicMemoryStore(backend, default_ttl_days=0)
    try:
        await backend.store(_episode("episode-a", namespace=namespace))
        await backend.store(_episode("episode-cross", namespace=other_namespace))
        await store.cite(["episode-a"], namespace=namespace, exposure_id="exposure-a")
        await store.cite(["episode-a"], namespace=namespace, exposure_id="exposure-old")

        with pytest.raises(ValueError, match="references are unavailable"):
            await store.cite(["episode-cross"], namespace=other_namespace, exposure_id="exposure-a")
        cited = await backend.get_citation("exposure-a")
        assert cited is not None
        assert [ref.memory_id for ref in cited.refs] == ["episode-a"]

        assert backend._db is not None
        await backend._db.execute(
            "UPDATE citations SET updated_at = ? WHERE exposure_id = ?",
            (datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat(), "exposure-old"),
        )
        await store.cite(["episode-a"], namespace=namespace, exposure_id="exposure-new")
        assert await backend.get_citation("exposure-old") is None
        assert await backend.get_citation("exposure-a") is not None
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_process_local_citations_are_bounded_without_durable_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify a backend without citation persistence keeps a bounded, least-recently-cited-first cache."""
    from parrot.memory.episodic import store as store_module

    class _NoCitationBackend(SQLiteEpisodeBackend):
        merge_citation = None  # type: ignore[assignment]
        get_citation = None  # type: ignore[assignment]

    monkeypatch.setattr(store_module, "_MAX_LOCAL_CITATIONS", 2)
    backend = _NoCitationBackend(tmp_path / "local.sqlite")
    await backend.configure()
    namespace = _namespace()
    store = EpisodicMemoryStore(backend, default_ttl_days=0)
    try:
        await backend.store(_episode("episode-a", namespace=namespace))
        for exposure_id in ("exposure-1", "exposure-2", "exposure-3"):
            await store.cite(["episode-a"], namespace=namespace, exposure_id=exposure_id)

        assert list(store._citations) == ["exposure-2", "exposure-3"]
        with pytest.raises(ValueError, match="scope or delivered exposure is unavailable"):
            await store.review(["episode-a"], _signal(), namespace=namespace, exposure_id="exposure-1")
        receipts = await store.review(["episode-a"], _signal(), namespace=namespace, exposure_id="exposure-3")
        assert [receipt.status for receipt in receipts] == ["applied"]
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_released_citation_is_rejected_and_deleted_durably(tmp_path: Path) -> None:
    """Verify a released exposure stops admitting reviews at once and its durable row is deleted."""
    path = tmp_path / "release.sqlite"
    namespace = _namespace()
    backend = SQLiteEpisodeBackend(path)
    other_backend = SQLiteEpisodeBackend(path)
    await backend.configure()
    await other_backend.configure()
    store = EpisodicMemoryStore(backend, default_ttl_days=0)
    try:
        await backend.store(_episode("episode-a", namespace=namespace))
        await store.cite(["episode-a"], namespace=namespace, exposure_id="exposure-a")
        await store.cite(["episode-a"], namespace=namespace, exposure_id="exposure-kept")
        assert await store.get_citation("exposure-a") is not None

        store.release_citation("exposure-a")
        assert await store.get_citation("exposure-a") is None
        with pytest.raises(ValueError, match="scope or delivered exposure is unavailable"):
            await store.review(["episode-a"], _signal(), namespace=namespace, exposure_id="exposure-a")

        assert await other_backend.get_citation("exposure-a") is None
        assert await other_backend.get_citation("exposure-kept") is not None
        assert not store._released_citations
    finally:
        await backend.close()
        await other_backend.close()


class _BaselineOnlyBackend:
    """Expose only the baseline protocol of a backend, hiding its optional read capabilities."""

    def __init__(self, backend: SQLiteEpisodeBackend) -> None:
        self._backend = backend
        self.store = backend.store
        self.search_similar = backend.search_similar
        self.get_recent = backend.get_recent
        self.get_failures = backend.get_failures
        self.delete_expired = backend.delete_expired
        self.count = backend.count
        self.update_metadata = backend.update_metadata


@pytest.mark.asyncio
async def test_store_routes_use_targeted_reads_and_match_full_scope_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With targeted reads the five routes skip the full-scope scan and answer like a backend without them."""
    namespace = _namespace()
    backend = SQLiteEpisodeBackend(tmp_path / "routes.sqlite")
    await backend.configure()
    monkeypatch.setattr("parrot.memory.episodic.store._LEXICAL_PAGE_SIZE", 2)
    full_scope_reads: list[str] = []
    pages: list[str | None] = []

    async def counted(namespace_filter: dict[str, object]) -> int:
        full_scope_reads.append("count")
        return await SQLiteEpisodeBackend.count(backend, namespace_filter)

    async def recent(*args: object, **kwargs: object) -> list[EpisodicMemory]:
        full_scope_reads.append("get_recent")
        return await SQLiteEpisodeBackend.get_recent(backend, *args, **kwargs)

    async def matching(namespace_filter: dict[str, object], **kwargs: object) -> list[EpisodicMemory]:
        if "limit" in kwargs:
            pages.append(kwargs.get("before_id"))
        return await SQLiteEpisodeBackend.get_recent_matching(backend, namespace_filter, **kwargs)

    try:
        for index in range(8):
            episode = _episode(f"episode-{index}", namespace=namespace)
            category = EpisodeCategory.USER_PREFERENCE if index in (1, 5) else EpisodeCategory.DECISION
            failed = index in (2, 6)
            await backend.store(
                episode.model_copy(
                    update={
                        "created_at": datetime(2026, 1, 1, 0, 0, index, tzinfo=timezone.utc),
                        "situation": f"Deploy release {index}" if index % 2 else f"Rotate key {index}",
                        "category": category,
                        "is_failure": failed,
                        "outcome": EpisodeOutcome.FAILURE if failed else EpisodeOutcome.SUCCESS,
                        "error_message": "boom" if failed else None,
                        "importance": index + 1,
                        "metadata": {"coder_feedback_retracted": True} if index == 5 else {},
                    }
                )
            )
        await backend.store(_episode("episode-cross", namespace=_namespace(tenant_id="tenant-b")))
        fallback = EpisodicMemoryStore(_BaselineOnlyBackend(backend), default_ttl_days=0)
        expected = {
            "resolved": sorted(await fallback._resolve_episodes(["episode-1", "episode-6"], namespace=namespace)),
            "warnings": await fallback.get_failure_warnings(namespace, max_warnings=5),
            "preferences": [episode.episode_id for episode in await fallback.get_user_preferences(namespace)],
            "room": [
                episode.episode_id
                for episode in await fallback.get_room_context(namespace, categories=[EpisodeCategory.DECISION])
            ],
            "room_all": [episode.episode_id for episode in await fallback.get_room_context(namespace, limit=20)],
            "lexical": [result.episode_id for result in await fallback.recall_similar("deploy release", namespace)],
            "lexical_failures": [
                result.episode_id
                for result in await fallback.recall_similar("rotate", namespace, include_failures_only=True)
            ],
        }
        # episode-5 is a retracted lesson: it matches the read and is dropped by every route afterwards.
        assert expected["preferences"] == ["episode-1"]
        assert expected["lexical"] == ["episode-7", "episode-3", "episode-1"]
        assert expected["lexical_failures"] == ["episode-6", "episode-2"]
        assert "Rotate key 6" in expected["warnings"] and "Rotate key 2" in expected["warnings"]

        monkeypatch.setattr(backend, "count", counted)
        monkeypatch.setattr(backend, "get_recent", recent)
        monkeypatch.setattr(backend, "get_recent_matching", matching)
        store = EpisodicMemoryStore(backend, default_ttl_days=0)

        assert sorted(await store._resolve_episodes(["episode-1", "episode-6"], namespace=namespace)) == (
            expected["resolved"]
        )
        for unavailable in ("episode-cross", "missing"):
            with pytest.raises(ValueError, match="references are unavailable"):
                await store._resolve_episodes(["episode-1", unavailable], namespace=namespace)
        assert await store.get_failure_warnings(namespace, max_warnings=5) == expected["warnings"]
        assert [episode.episode_id for episode in await store.get_user_preferences(namespace)] == (
            expected["preferences"]
        )
        assert [
            episode.episode_id
            for episode in await store.get_room_context(namespace, categories=[EpisodeCategory.DECISION])
        ] == expected["room"]
        assert [result.episode_id for result in await store.recall_similar("deploy release", namespace)] == (
            expected["lexical"]
        )
        assert [
            result.episode_id for result in await store.recall_similar("rotate", namespace, include_failures_only=True)
        ] == expected["lexical_failures"]
        assert full_scope_reads == []

        # Paging stops as soon as the requested matches are found: the two newest pages hold both of them.
        pages.clear()
        newest = await store.recall_similar("deploy release", namespace, top_k=2)
        assert [result.episode_id for result in newest] == [
            result.episode_id for result in await fallback.recall_similar("deploy release", namespace, top_k=2)
        ]
        assert [result.episode_id for result in newest] == ["episode-7"]
        assert pages == [None, "episode-6"]

        # Without a category there is nothing to select, so the cache-aware full-scope read stays.
        assert [episode.episode_id for episode in await store.get_room_context(namespace, limit=20)] == (
            expected["room_all"]
        )
        assert full_scope_reads == ["count", "get_recent"]
    finally:
        await backend.close()
