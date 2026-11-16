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

from parrot.memory.episodic.backends import sqlite as sqlite_backend
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
async def test_measured_ceiling_reports_degradation(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify over-ceiling vector search reports degradation without lexical substitution."""
    backend = SQLiteEpisodeBackend(tmp_path / "episodes.sqlite", vector_ceiling=2)
    await backend.configure()
    warnings: list[str] = []
    monkeypatch.setattr(
        sqlite_backend.logger, "warning", lambda message, *arguments: warnings.append(message % arguments)
    )
    try:
        for index in range(2):
            await backend.store(_episode(index))
        at_ceiling = await backend.search_similar([1.0, 0.0], {"tenant_id": "tenant-a", "agent_id": "agent-a"}, top_k=5)
        assert [result.episode_id for result in at_ceiling] == ["episode-1", "episode-0"]
        assert warnings == []

        await backend.store(_episode(2))
        status = await backend.vector_status({"tenant_id": "tenant-a", "agent_id": "agent-a"})
        results = await backend.search_similar([1.0, 0.0], {"tenant_id": "tenant-a", "agent_id": "agent-a"}, top_k=5)

        assert status == {"status": "degraded", "candidate_count": 3, "vector_ceiling": 2}
        assert [result.episode_id for result in results] == ["episode-2", "episode-1"]
        # D7: truncation is logged once per search, naming the scope dimensions and never their values.
        assert len(warnings) == 1
        assert "more than 2 candidates" in warnings[0]
        assert "agent_id, tenant_id" in warnings[0]
        assert "tenant-a" not in warnings[0] and "agent-a" not in warnings[0]
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
async def test_outcome_revisions_are_scoped_to_requester(tmp_path) -> None:
    """Shared agent-level state does not merge independent callers' outcome revision streams."""
    backend = SQLiteEpisodeBackend(tmp_path / "scoped-outcomes.sqlite")
    await backend.configure()
    namespace = MemoryNamespace(tenant_id="tenant-a", agent_id="agent-a")
    try:
        await backend.store(_episode(1))
        template = _review_command(namespace, episode_id="episode-1", outcome_id="same")

        def command(user: str | None, session: str | None, revision: int, expected: int) -> ReviewCommand:
            """Build a validated command preserving original ref and requesting identity."""
            data = template.model_dump()
            data["signal"]["scope"].update(user_id=user, session_id=session)
            data["signal"]["outcome_revision"] = revision
            data["expected_revision"] = expected
            return ReviewCommand.model_validate(data)

        first = command("u1", "s1", 5, 0)
        assert (await backend.apply_review(first)).status == "applied"
        for expected, (user, session) in enumerate([("u1", "s2"), ("u2", "s1"), (None, None)], 1):
            assert (await backend.apply_review(command(user, session, 0, expected))).status == "applied"
        assert (await backend.apply_review(command("u1", "s1", 4, 4))).status == "stale_revision"
        assert (await backend.apply_review(first)).status == "duplicate"
        assert backend._db is not None
        assert (await (await backend._db.execute("SELECT COUNT(*) FROM memory_state")).fetchone())[0] == 1
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


@pytest.mark.asyncio
async def test_compact_embeddings_hydrate_every_public_read_path(tmp_path: Path) -> None:
    """Compact rows hydrate float32 embeddings through every public episode read."""
    path = tmp_path / "compact.sqlite"
    backend = SQLiteEpisodeBackend(path)
    compact_vector = [0.123456789, -0.987654321, 0.5]
    await backend.configure()
    try:
        compact = _episode(1, embedding=compact_vector, situation="needle compact")
        none_vector = _episode(2, embedding=None, situation="needle none")
        failure = _episode(3, embedding=[0.0, 1.0, 0.0], is_failure=True, situation="needle failure")
        await backend.store(compact)
        await backend.store(none_vector)
        await backend.store(failure)

        assert compact.embedding == compact_vector
        assert backend._db is not None
        cursor = await backend._db.execute(
            "SELECT payload, embedding, embedding_dim FROM episodes WHERE episode_id = ?", (compact.episode_id,)
        )
        compact_payload, compact_blob, compact_dimension = await cursor.fetchone()
        assert "embedding" not in json.loads(compact_payload)
        assert isinstance(compact_blob, bytes)
        assert compact_dimension == len(compact_vector)
        expected_float32 = list(struct.unpack(f"<{compact_dimension}f", compact_blob))

        cursor = await backend._db.execute(
            "SELECT payload, embedding, embedding_dim FROM episodes WHERE episode_id = ?", (none_vector.episode_id,)
        )
        none_payload, none_blob, none_dimension = await cursor.fetchone()
        assert "embedding" not in json.loads(none_payload)
        assert (none_blob, none_dimension) == (None, None)

        vector_results = await backend.search_similar(compact_vector, _SCOPE, top_k=1, score_threshold=0.0)
        assert vector_results[0].embedding == expected_float32

        fts_results = await backend.search_text("needle", _SCOPE, top_k=3)
        assert {result.episode_id: result.embedding for result in fts_results} == {
            compact.episode_id: expected_float32,
            none_vector.episode_id: None,
            failure.episode_id: [0.0, 1.0, 0.0],
        }

        backend._fts_enabled = False
        like_results = await backend.search_text("needle", _SCOPE, top_k=3)
        assert {result.episode_id: result.embedding for result in like_results} == {
            compact.episode_id: expected_float32,
            none_vector.episode_id: None,
            failure.episode_id: [0.0, 1.0, 0.0],
        }

        recent = {episode.episode_id: episode.embedding for episode in await backend.get_recent(_SCOPE)}
        by_id = {
            episode.episode_id: episode.embedding
            for episode in await backend.get_by_ids([compact.episode_id, none_vector.episode_id], _SCOPE)
        }
        matching = {episode.episode_id: episode.embedding for episode in await backend.get_recent_matching(_SCOPE)}
        failures = {
            episode.episode_id: episode.embedding for episode in await backend.get_failures("agent-a", "tenant-a")
        }
        assert recent[compact.episode_id] == expected_float32
        assert by_id == {compact.episode_id: expected_float32, none_vector.episode_id: None}
        assert matching[compact.episode_id] == expected_float32
        assert failures == {failure.episode_id: [0.0, 1.0, 0.0]}

        assert await backend.update_metadata([compact.episode_id], {"source": "test"}) == 1
        cursor = await backend._db.execute("SELECT payload FROM episodes WHERE episode_id = ?", (compact.episode_id,))
        updated_payload = json.loads((await cursor.fetchone())[0])
        assert "embedding" not in updated_payload
        assert updated_payload["metadata"]["source"] == "test"
    finally:
        await backend.close()

    reopened = SQLiteEpisodeBackend(path)
    await reopened.configure()
    try:
        restored = await reopened.get_by_ids([compact.episode_id, none_vector.episode_id], _SCOPE)
        assert {episode.episode_id: episode.embedding for episode in restored} == {
            compact.episode_id: expected_float32,
            none_vector.episode_id: None,
        }
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_compact_payload_size_and_legacy_embedding_precedence(tmp_path: Path) -> None:
    """Compact writes stay size-stable while legacy JSON vectors remain authoritative."""
    path = tmp_path / "legacy.sqlite"
    backend = SQLiteEpisodeBackend(path)
    await backend.configure()
    try:
        small = _episode(4, episode_id="small", situation="same", action_taken="same", embedding=[0.1, 0.2])
        large = _episode(
            5,
            episode_id="large",
            situation="same",
            action_taken="same",
            embedding=[0.1] * 256,
        )
        legacy_vector = _episode(6, embedding=[0.123456789123, -0.987654321987])
        legacy_none = _episode(7, embedding=None)
        for episode in (small, large, legacy_vector, legacy_none):
            await backend.store(episode)

        assert backend._db is not None
        cursor = await backend._db.execute(
            "SELECT episode_id, payload FROM episodes WHERE episode_id IN (?, ?) ORDER BY episode_id",
            (small.episode_id, large.episode_id),
        )
        compact_rows = await cursor.fetchall()
        assert len(compact_rows[0][1]) == len(compact_rows[1][1])
        assert all("embedding" not in json.loads(row[1]) for row in compact_rows)

        legacy_payload = json.dumps(legacy_vector.to_dict())
        legacy_none_data = legacy_none.to_dict()
        legacy_none_data["embedding"] = None
        legacy_none_payload = json.dumps(legacy_none_data)
        await backend._db.execute(
            "UPDATE episodes SET payload = ?, embedding = ?, embedding_dim = ? WHERE episode_id = ?",
            (legacy_payload, b"corrupt", 1, legacy_vector.episode_id),
        )
        await backend._db.execute(
            "UPDATE episodes SET payload = ?, embedding = ?, embedding_dim = ? WHERE episode_id = ?",
            (legacy_none_payload, struct.pack("<2f", 3.0, 4.0), 2, legacy_none.episode_id),
        )
        await backend._db.commit()

        await backend.store(_episode(6, embedding=[9.0, 9.0]))
        restored = await backend.get_by_ids([legacy_vector.episode_id, legacy_none.episode_id], _SCOPE)
        assert {episode.episode_id: episode.embedding for episode in restored} == {
            legacy_vector.episode_id: legacy_vector.embedding,
            legacy_none.episode_id: None,
        }

        assert await backend.update_metadata([legacy_vector.episode_id], {"checked": True}) == 1
        cursor = await backend._db.execute(
            "SELECT payload FROM episodes WHERE episode_id = ?", (legacy_vector.episode_id,)
        )
        persisted_legacy = json.loads((await cursor.fetchone())[0])
        assert persisted_legacy["embedding"] == legacy_vector.embedding
        assert persisted_legacy["metadata"]["checked"] is True
    finally:
        await backend.close()

    reopened = SQLiteEpisodeBackend(path)
    await reopened.configure()
    try:
        restored = await reopened.get_by_ids([legacy_vector.episode_id, legacy_none.episode_id], _SCOPE)
        assert {episode.episode_id: episode.embedding for episode in restored} == {
            legacy_vector.episode_id: legacy_vector.embedding,
            legacy_none.episode_id: None,
        }
    finally:
        await reopened.close()


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


@pytest.mark.parametrize(
    ("blob", "dimension"),
    [
        pytest.param(b"\x00\x00\x00", 2, id="malformed-shape"),
        pytest.param(None, 2, id="null-blob"),
        pytest.param("not-a-blob", 2, id="non-blob-type"),
        pytest.param(struct.pack("<2f", 0.0, 1.0), None, id="null-dimension"),
        pytest.param(struct.pack("<2f", 0.0, 1.0), "two", id="non-integer-dimension"),
        pytest.param(struct.pack("<2f", 0.0, 1.0), 0, id="zero-dimension"),
        pytest.param(struct.pack("<2f", 0.0, 1.0), -1, id="negative-dimension"),
        pytest.param(struct.pack("<2f", math.nan, 0.0), 2, id="nan-vector"),
        pytest.param(struct.pack("<2f", math.inf, 0.0), 2, id="infinite-vector"),
    ],
)
@pytest.mark.asyncio
async def test_vector_scoring_skips_malformed_and_non_finite_vectors(
    tmp_path, monkeypatch: pytest.MonkeyPatch, blob: bytes | str | None, dimension: object
) -> None:
    """Corrupt stored vectors are skipped without excluding valid scoped candidates."""
    backend = SQLiteEpisodeBackend(tmp_path / "corrupt.sqlite")
    await backend.configure()
    warnings: list[str] = []
    monkeypatch.setattr(
        sqlite_backend.logger, "warning", lambda message, *arguments: warnings.append(message % arguments)
    )
    try:
        await backend.store(_episode(1, embedding=[1.0, 0.0]))
        await backend.store(_episode(2, embedding=[0.0, 1.0]))
        await backend.store(_episode(3, embedding=[1.0, 0.0, 0.0]))
        assert backend._db is not None

        async def corrupt(episode_id: str) -> None:
            await backend._db.execute(
                "UPDATE episodes SET embedding = ?, embedding_dim = ? WHERE episode_id = ?",
                (blob, dimension, episode_id),
            )

        await corrupt("episode-2")
        results = await backend.search_similar([1.0, 0.0], _SCOPE, top_k=3, score_threshold=0.0)
        assert [result.episode_id for result in results] == ["episode-1", "episode-3"]
        assert [result.score for result in results] == [1.0, 0.0]
        assert warnings == ["Skipped 1 corrupt stored vector candidates during vector search"]

        zero_query = await backend.search_similar([0.0, 0.0], _SCOPE, top_k=3, score_threshold=0.0)
        assert [result.episode_id for result in zero_query] == ["episode-3", "episode-1"]
        assert [result.score for result in zero_query] == [0.0, 0.0]

        await corrupt("episode-1")
        await corrupt("episode-3")
        assert await backend.search_similar([1.0, 0.0], _SCOPE, top_k=3, score_threshold=0.0) == []
        assert warnings[-1] == "Skipped 3 corrupt stored vector candidates during vector search"
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

    Rows have the compact layout ``store()`` writes: embeddings live only in the float32 blob at the production
    dimension. The contract is defined on otherwise idle reference hardware, so a round disturbed by concurrent load
    may be measured again.
    """
    path = tmp_path / "ceiling.sqlite"
    backend = SQLiteEpisodeBackend(path)
    await backend.configure()
    try:
        generator = np.random.default_rng(892)
        vectors = generator.standard_normal((_CEILING_ROWS, _PRODUCTION_DIMENSION), dtype=np.float32)
        template = json.dumps(
            _episode(0, episode_id="EPISODE-ID", embedding=vectors[0].tolist()).model_dump(mode="json")
        )
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


@pytest.mark.asyncio
async def test_list_reviews_follows_commit_order_when_clock_steps_back(tmp_path) -> None:
    """Reviews are listed in commit order even when a later commit carries an earlier wall-clock time."""
    backend = SQLiteEpisodeBackend(tmp_path / "order.sqlite")
    namespace = MemoryNamespace(tenant_id="tenant-a", agent_id="agent-a")
    await backend.configure()
    try:
        await backend.store(_episode(1))
        for revision, outcome_id in enumerate(("first", "second", "third")):
            command = _review_command(
                namespace, episode_id="episode-1", outcome_id=outcome_id, expected_revision=revision
            )
            assert (await backend.apply_review(command)).status == "applied"
        assert backend._db is not None
        # The process that committed "second" and "third" had a clock behind the one that committed "first".
        for outcome_id, recorded_at in (("first", "2026-03-01"), ("second", "2026-01-01"), ("third", "2026-02-01")):
            await backend._db.execute(
                "UPDATE reviews SET recorded_at = ? WHERE outcome_id = ?", (f"{recorded_at}T00:00:00+00:00", outcome_id)
            )

        listed = await backend.list_reviews(namespace)
        limited = await backend.list_reviews(namespace, limit=2)

        assert [row["outcome_id"] for row in listed] == ["first", "second", "third"]
        assert [row["apply_revision"] for row in listed] == [1, 2, 3]
        assert [row["outcome_id"] for row in limited] == ["first", "second"]
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_apply_review_requires_exact_episode_scope(tmp_path) -> None:
    """A ref that leaves a dimension unset cannot review an episode that sets it."""
    backend = SQLiteEpisodeBackend(tmp_path / "exact-scope.sqlite")
    agent_level = MemoryNamespace(tenant_id="tenant-a", agent_id="agent-a")
    user_level = MemoryNamespace(tenant_id="tenant-a", agent_id="agent-a", user_id="user-a")
    await backend.configure()
    try:
        await backend.store(_episode(1, user_id="user-a"))
        await backend.store(_episode(2))

        broader = await backend.apply_review(_review_command(agent_level, episode_id="episode-1", outcome_id="broad"))
        narrower = await backend.apply_review(_review_command(user_level, episode_id="episode-2", outcome_id="narrow"))

        assert (broader.status, broader.reason) == ("ignored", "memory ref is unavailable")
        assert (narrower.status, narrower.reason) == ("ignored", "memory ref is unavailable")
        assert backend._db is not None
        for table in ("reviews", "memory_state"):
            cursor = await backend._db.execute(f"SELECT COUNT(*) FROM {table}")
            assert (await cursor.fetchone())[0] == 0

        exact = await backend.apply_review(_review_command(user_level, episode_id="episode-1", outcome_id="exact"))
        assert exact.status == "applied"
        assert [row["outcome_id"] for row in await backend.list_reviews(user_level)] == ["exact"]
    finally:
        await backend.close()
