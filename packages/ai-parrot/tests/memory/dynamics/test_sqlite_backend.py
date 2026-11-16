"""Behavioral acceptance tests for SQLite episodic persistence and measured vector ceiling."""

import asyncio
import json
import math
import sqlite3
import struct
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend
from parrot.memory.dynamics.models import Grade, MemoryParameters, ReviewCommand
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


def _parameters(parameter_id: str = "episodic-neutral-v1") -> MemoryParameters:
    """Build accepted parameters for persisted-review record tests."""
    return MemoryParameters(
        algorithm="fsrs-6",
        time_policy="days-v1",
        parameter_id=parameter_id,
        provenance="test-sqlite-review",
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


@pytest.mark.asyncio
async def test_review_schema_migration_preserves_legacy_rows_and_completes_partial_schema(tmp_path) -> None:
    """A v2 archive upgrades additively without inventing a persisted review record."""
    namespace = MemoryNamespace(tenant_id="tenant-a", agent_id="agent-a")
    command = _review_command(namespace, episode_id="legacy-episode", outcome_id="legacy")
    legacy_path = tmp_path / "legacy-v2.sqlite"
    connection = sqlite3.connect(legacy_path)
    try:
        connection.executescript("""
            CREATE TABLE reviews (
                dedupe_key TEXT PRIMARY KEY,
                outcome_id TEXT NOT NULL,
                outcome_revision INTEGER NOT NULL,
                ref_key TEXT NOT NULL,
                payload_digest TEXT NOT NULL,
                payload TEXT NOT NULL,
                apply_revision INTEGER NOT NULL,
                recorded_at TEXT NOT NULL
            );
            CREATE TABLE memory_state (
                ref_key TEXT PRIMARY KEY,
                apply_revision INTEGER NOT NULL,
                state TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            PRAGMA user_version = 2;
            """)
        payload = json.dumps(command.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        state = json.dumps({"apply_revision": 1, "command": command.model_dump(mode="json")})
        connection.execute(
            "INSERT INTO reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                command.dedupe_key,
                command.signal.outcome_id,
                command.signal.outcome_revision,
                command.ref.canonical_key,
                command.payload_digest,
                payload,
                1,
                "2026-01-02T00:00:00+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO memory_state VALUES (?, ?, ?, ?)",
            (command.ref.canonical_key, 1, state, "2026-01-02T00:00:00+00:00"),
        )
        connection.commit()
    finally:
        connection.close()

    backend = SQLiteEpisodeBackend(legacy_path)
    await backend.configure()
    try:
        rows = await backend.list_reviews(namespace)
        assert len(rows) == 1
        assert "record" not in rows[0]
        assert backend._db is not None
        version = await (await backend._db.execute("PRAGMA user_version")).fetchone()
        columns = await (await backend._db.execute("PRAGMA table_info(reviews)")).fetchall()
        assert version == (3,)
        assert {row[1] for row in columns} >= {
            "grade",
            "before_state",
            "after_state",
            "parameter_id",
            "memory_error_signature",
        }
    finally:
        await backend.close()

    reopened = SQLiteEpisodeBackend(legacy_path)
    await reopened.configure()
    try:
        assert "record" not in (await reopened.list_reviews(namespace))[0]
    finally:
        await reopened.close()

    partial_path = tmp_path / "partial-v2.sqlite"
    connection = sqlite3.connect(partial_path)
    try:
        connection.executescript("""
            CREATE TABLE reviews (
                dedupe_key TEXT PRIMARY KEY,
                outcome_id TEXT NOT NULL,
                outcome_revision INTEGER NOT NULL,
                ref_key TEXT NOT NULL,
                payload_digest TEXT NOT NULL,
                payload TEXT NOT NULL,
                apply_revision INTEGER NOT NULL,
                recorded_at TEXT NOT NULL,
                grade INTEGER
            );
            PRAGMA user_version = 2;
            """)
        connection.commit()
    finally:
        connection.close()
    partial = SQLiteEpisodeBackend(partial_path)
    await partial.configure()
    try:
        assert partial._db is not None
        columns = await (await partial._db.execute("PRAGMA table_info(reviews)")).fetchall()
        assert {row[1] for row in columns} >= {
            "grade",
            "before_state",
            "after_state",
            "parameter_id",
            "memory_error_signature",
        }
    finally:
        await partial.close()


@pytest.mark.asyncio
async def test_apply_review_persists_record_and_rolls_back_transition_failure(tmp_path) -> None:
    """Review records and state are committed together, or neither mutation persists."""
    backend = SQLiteEpisodeBackend(tmp_path / "record.sqlite")
    namespace = MemoryNamespace(tenant_id="tenant-a", agent_id="agent-a")
    await backend.configure()
    try:
        await backend.store(_episode(1))
        first_command = _review_command(namespace, episode_id="episode-1", outcome_id="first")
        first = await backend.apply_review(
            first_command,
            grade=Grade.GOOD,
            memory_error_signature="x" * 2_001,
            parameters=_parameters(),
        )
        assert first.status == "applied"
        first_row = (await backend.list_reviews(namespace))[0]
        assert first_row["record"]["grade"] == int(Grade.GOOD)
        assert first_row["record"]["before"]["status"] == "uninitialized"
        assert first_row["record"]["after"]["status"] == "reviewed"
        assert first_row["record"]["memory_error_signature"] == "x" * 2_000

        second_command = _review_command(namespace, episode_id="episode-1", outcome_id="second", expected_revision=1)
        assert (
            await backend.apply_review(second_command, grade=Grade.HARD, parameters=_parameters())
        ).status == "applied"
        records = await backend.list_reviews(namespace)
        assert records[1]["record"]["before"] == records[0]["record"]["after"]

        failing_command = _review_command(namespace, episode_id="episode-1", outcome_id="failing", expected_revision=2)
        with pytest.raises(ValueError, match="parameter_id"):
            await backend.apply_review(
                failing_command,
                grade=Grade.GOOD,
                parameters=_parameters("different-parameter"),
            )
        assert len(await backend.list_reviews(namespace)) == 2
        state = await (await backend._db.execute("SELECT apply_revision FROM memory_state")).fetchone()
        assert state == (2,)
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_apply_review_without_record_keywords_remains_legacy(tmp_path) -> None:
    """Legacy direct callers write nullable record columns and retain existing receipts."""
    backend = SQLiteEpisodeBackend(tmp_path / "legacy-call.sqlite")
    namespace = MemoryNamespace(tenant_id="tenant-a", agent_id="agent-a")
    await backend.configure()
    try:
        await backend.store(_episode(1))
        command = _review_command(namespace, episode_id="episode-1", outcome_id="legacy")
        with pytest.raises(ValueError, match="grade and parameters"):
            await backend.apply_review(command, grade=Grade.GOOD)
        assert (await backend.apply_review(command)).status == "applied"
        assert "record" not in (await backend.list_reviews(namespace))[0]
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_get_memory_states_reads_committed_state_by_exact_ref(tmp_path) -> None:
    """Earned state is readable by its canonical ref key only, and a stateless review exposes none."""
    backend = SQLiteEpisodeBackend(tmp_path / "state-read.sqlite")
    namespace = MemoryNamespace(tenant_id="tenant-a", agent_id="agent-a")
    other_namespace = MemoryNamespace(tenant_id="tenant-b", agent_id="agent-a")
    with pytest.raises(RuntimeError, match="not configured"):
        await backend.get_memory_states(["mref-v1-missing"])
    await backend.configure()
    try:
        await backend.store(_episode(1))
        await backend.store(_episode(2))
        reviewed = _review_command(namespace, episode_id="episode-1", outcome_id="graded")
        legacy = _review_command(namespace, episode_id="episode-2", outcome_id="legacy")
        cross_scope = _review_command(other_namespace, episode_id="episode-1", outcome_id="graded")
        assert (await backend.apply_review(reviewed, grade=Grade.GOOD, parameters=_parameters())).status == "applied"
        assert (await backend.apply_review(legacy)).status == "applied"

        assert await backend.get_memory_states([]) == {}
        states = await backend.get_memory_states(
            [
                reviewed.ref.canonical_key,
                reviewed.ref.canonical_key,
                legacy.ref.canonical_key,
                cross_scope.ref.canonical_key,
                "mref-v1-missing",
            ]
        )

        assert list(states) == [reviewed.ref.canonical_key]
        state = states[reviewed.ref.canonical_key]
        assert state.status == "reviewed"
        assert state.review_count == 1
        assert state.parameter_id == "episodic-neutral-v1"
        assert state.stability is not None and state.stability > 0

        many = [f"mref-v1-absent-{index}" for index in range(1_200)] + [reviewed.ref.canonical_key]
        assert list(await backend.get_memory_states(many)) == [reviewed.ref.canonical_key]
    finally:
        await backend.close()


_SCOPE = {"tenant_id": "tenant-a", "agent_id": "agent-a"}


def _reference_cosine(query: list[float], stored: list[float]) -> float:
    """Score one float32-stored vector the way the pre-numpy implementation did."""
    rounded = list(struct.unpack(f"<{len(stored)}f", struct.pack(f"<{len(stored)}f", *stored)))
    if len(query) != len(rounded):
        return 0.0
    query_norm = math.sqrt(sum(value * value for value in query))
    stored_norm = math.sqrt(sum(value * value for value in rounded))
    if query_norm == 0.0 or stored_norm == 0.0:
        return 0.0
    return sum(left * right for left, right in zip(query, rounded, strict=True)) / (query_norm * stored_norm)


@pytest.mark.asyncio
async def test_vector_scoring_matches_reference_semantics(tmp_path) -> None:
    """Vectorized scoring keeps the scores, the zero cases, the tie order and both limits of exact search."""
    backend = SQLiteEpisodeBackend(tmp_path / "scoring.sqlite")
    await backend.configure()
    query = [0.3, -0.2, 0.9, 0.1, -0.5]
    vectors = {
        0: [0.3, -0.2, 0.9, 0.1, -0.5],
        1: [0.9, 0.4, 0.1, -0.3, 0.2],
        2: [-0.3, 0.2, -0.9, -0.1, 0.5],
        3: [0.0, 0.0, 0.0, 0.0, 0.0],
        4: [1.0, 0.0, 0.0],
        5: [0.25, -0.1, 0.7, 0.3, -0.6],
        6: [0.3, -0.2, 0.9, 0.1, -0.5],
    }
    try:
        for index, vector in vectors.items():
            await backend.store(_episode(index, embedding=vector))
        expected = {f"episode-{index}": _reference_cosine(query, vector) for index, vector in vectors.items()}

        everything = await backend.search_similar(query, _SCOPE, top_k=10, score_threshold=0.0)

        # The opposite vector scores below zero; equal scores keep the newest episode first.
        assert [result.episode_id for result in everything] == [
            "episode-6",
            "episode-0",
            "episode-5",
            "episode-1",
            "episode-4",
            "episode-3",
        ]
        assert [result.score for result in everything] == pytest.approx(
            [expected[result.episode_id] for result in everything], abs=1e-12
        )
        assert expected["episode-2"] < 0.0
        assert everything[0].score == everything[1].score
        assert [result.score for result in everything[-2:]] == [0.0, 0.0]

        above = await backend.search_similar(query, _SCOPE, top_k=10, score_threshold=0.5)
        assert [result.episode_id for result in above] == ["episode-6", "episode-0", "episode-5"]
        best = await backend.search_similar(query, _SCOPE, top_k=1, score_threshold=0.0)
        assert [result.episode_id for result in best] == ["episode-6"]
        assert await backend.search_similar([0.0] * 5, _SCOPE, top_k=10, score_threshold=0.1) == []
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_vector_scoring_rejects_malformed_and_non_finite_vectors(tmp_path) -> None:
    """A corrupt stored vector fails the search visibly instead of being scored or skipped."""
    backend = SQLiteEpisodeBackend(tmp_path / "corrupt.sqlite")
    await backend.configure()
    try:
        await backend.store(_episode(1))
        await backend.store(_episode(2))
        assert backend._db is not None

        async def corrupt(blob: bytes, dimension: int) -> None:
            await backend._db.execute(
                "UPDATE episodes SET embedding = ?, embedding_dim = ? WHERE episode_id = 'episode-2'",
                (blob, dimension),
            )

        await corrupt(b"\x00\x00\x00", 2)
        with pytest.raises(ValueError, match="stored embedding has an invalid shape"):
            await backend.search_similar([1.0, 0.0], _SCOPE)
        await corrupt(struct.pack("<2f", math.inf, 0.0), 2)
        with pytest.raises(ValueError, match="stored embedding values must be finite"):
            await backend.search_similar([1.0, 0.0], _SCOPE)
        await corrupt(struct.pack("<3f", math.nan, 0.0, 0.0), 3)
        with pytest.raises(ValueError, match="stored embedding values must be finite"):
            await backend.search_similar([1.0, 0.0], _SCOPE)
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_vector_search_scores_off_the_event_loop_and_reads_winning_payloads_only(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scoring runs in a worker thread, and a losing candidate never has its payload read."""
    backend = SQLiteEpisodeBackend(tmp_path / "dispatch.sqlite")
    await backend.configure()
    dispatched: list[str] = []
    statements: list[str] = []
    to_thread = asyncio.to_thread

    async def recording_to_thread(function, /, *args, **kwargs):
        dispatched.append(function.__name__)
        return await to_thread(function, *args, **kwargs)

    try:
        await backend.store(_episode(1, embedding=[0.0, 1.0]))
        await backend.store(_episode(2, embedding=[1.0, 0.0]))
        await backend.store(_episode(3, embedding=[0.6, 0.8]))
        assert backend._db is not None
        monkeypatch.setattr(asyncio, "to_thread", recording_to_thread)
        await backend._db.set_trace_callback(statements.append)

        results = await backend.search_similar([1.0, 0.0], _SCOPE, top_k=1)

        await backend._db.set_trace_callback(None)
        assert [result.episode_id for result in results] == ["episode-2"]
        assert dispatched == ["_rank_candidates"]
        selects = [statement for statement in statements if statement.lstrip().upper().startswith("SELECT")]
        assert len(selects) == 2
        assert "payload" not in selects[0]
        assert "payload" in selects[1] and "episode-2" in selects[1]
        assert "episode-1" not in selects[1] and "episode-3" not in selects[1]
    finally:
        await backend.close()


_CEILING_ROWS = 5_000
_PRODUCTION_DIMENSION = 1_536
_LATENCY_BUDGET_SECONDS = 0.150


@pytest.mark.asyncio
async def test_vector_search_meets_latency_contract_at_ceiling(tmp_path) -> None:
    """D6/AC13: exact search over the 5,000-row ceiling answers within p95 <= 150 ms.

    Rows have the layout ``store()`` writes, where the payload carries the embedding as JSON, at the dimension of a
    production embedding. The contract is defined on otherwise idle reference hardware, so a round disturbed by
    concurrent load may be measured again.
    """
    path = tmp_path / "ceiling.sqlite"
    backend = SQLiteEpisodeBackend(path)
    await backend.configure()
    try:
        generator = np.random.default_rng(892)
        vectors = generator.standard_normal((_CEILING_ROWS, _PRODUCTION_DIMENSION), dtype=np.float32)
        template = json.dumps(_episode(0, episode_id="EPISODE-ID", embedding=vectors[0].tolist()).to_dict())
        started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert backend._db is not None
        await backend._db.execute("BEGIN")
        await backend._db.executemany(
            "INSERT INTO episodes (episode_id, tenant_id, agent_id, created_at, is_failure, payload, embedding, "
            "embedding_dim) VALUES (?, 'tenant-a', 'agent-a', ?, 0, ?, ?, ?)",
            [
                (
                    f"episode-{index}",
                    (started_at + timedelta(seconds=index)).isoformat(),
                    template.replace("EPISODE-ID", f"episode-{index}"),
                    vectors[index].tobytes(),
                    _PRODUCTION_DIMENSION,
                )
                for index in range(_CEILING_ROWS)
            ],
        )
        await backend._db.execute("COMMIT")
        query = generator.standard_normal(_PRODUCTION_DIMENSION)
        cosines = (vectors @ query) / (np.linalg.norm(vectors.astype(np.float64), axis=1) * np.linalg.norm(query))

        status = await backend.vector_status(_SCOPE)
        results = await backend.search_similar(query.tolist(), _SCOPE, top_k=5, score_threshold=0.0)

        assert status == {"status": "ok", "candidate_count": _CEILING_ROWS, "vector_ceiling": _CEILING_ROWS}
        assert results[0].episode_id == f"episode-{int(np.argmax(cosines))}"
        assert results[0].score == pytest.approx(float(np.max(cosines)), abs=1e-6)

        rounds: list[float] = []
        for _ in range(3):
            samples: list[float] = []
            for _ in range(20):
                started = time.perf_counter()
                await backend.search_similar(query.tolist(), _SCOPE, top_k=5, score_threshold=0.0)
                samples.append(time.perf_counter() - started)
            rounds.append(sorted(samples)[18])
            if rounds[-1] <= _LATENCY_BUDGET_SECONDS:
                break
        assert min(rounds) <= _LATENCY_BUDGET_SECONDS, f"p95 per round (s): {rounds}"
    finally:
        await backend.close()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{path}{suffix}").unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_get_by_ids_and_recent_matching_filter_in_sql(tmp_path) -> None:
    """Targeted reads select by id, category, failure and page without leaving the scope."""
    backend = SQLiteEpisodeBackend(tmp_path / "targeted.sqlite")
    await backend.configure()
    try:
        await backend.store(_episode(1))
        await backend.store(_episode(2, outcome="failure", is_failure=True))
        await backend.store(_episode(3, category="user_preference"))
        await backend.store(_episode(4, category="decision", outcome="failure", is_failure=True))
        await backend.store(_episode(5, tenant_id="tenant-b", category="user_preference"))

        def ids(episodes: list[EpisodicMemory]) -> list[str]:
            return [episode.episode_id for episode in episodes]

        assert await backend.get_by_ids([], _SCOPE) == []
        assert ids(
            await backend.get_by_ids(["episode-1", "episode-3", "episode-1", "episode-5", "missing"], _SCOPE)
        ) == ["episode-3", "episode-1"]
        many = [f"absent-{index}" for index in range(1_200)] + ["episode-2"]
        assert ids(await backend.get_by_ids(many, _SCOPE)) == ["episode-2"]
        assert ids(await backend.get_by_ids(["episode-1"], {**_SCOPE, "user_id": None})) == ["episode-1"]
        assert await backend.get_by_ids(["episode-1"], {**_SCOPE, "user_id": "user-a"}) == []

        assert ids(await backend.get_recent_matching(_SCOPE)) == ["episode-4", "episode-3", "episode-2", "episode-1"]
        assert ids(await backend.get_recent_matching(_SCOPE, categories=["user_preference"])) == ["episode-3"]
        assert ids(await backend.get_recent_matching(_SCOPE, categories=["user_preference", "decision"])) == [
            "episode-4",
            "episode-3",
        ]
        assert await backend.get_recent_matching(_SCOPE, categories=[]) == []
        assert ids(await backend.get_recent_matching(_SCOPE, failures_only=True)) == ["episode-4", "episode-2"]
        assert ids(await backend.get_recent_matching(_SCOPE, categories=["decision"], failures_only=True)) == [
            "episode-4"
        ]

        first_page = await backend.get_recent_matching(_SCOPE, limit=2)
        assert ids(first_page) == ["episode-4", "episode-3"]
        assert ids(await backend.get_recent_matching(_SCOPE, limit=2, before_id=first_page[-1].episode_id)) == [
            "episode-2",
            "episode-1",
        ]
        assert await backend.get_recent_matching(_SCOPE, before_id="episode-1") == []
        assert await backend.get_recent_matching(_SCOPE, before_id="missing") == []
        assert await backend.get_recent_matching(_SCOPE, limit=0) == []
        with pytest.raises(ValueError, match="limit must be non-negative"):
            await backend.get_recent_matching(_SCOPE, limit=-1)
    finally:
        await backend.close()
