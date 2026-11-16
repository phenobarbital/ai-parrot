"""Behavioral acceptance tests for user forgetting, suppression and derivative retry."""

from pathlib import Path

import aiosqlite
import pytest

from parrot.memory.agent_memory.models import ChatStorageEvidenceRef, MemoryRequestScope
from parrot.memory.user.models import UserKnowledgeCandidate, UserKnowledgeCommand
from parrot.memory.user.store import UserMemoryStore


def _scope(*, tenant_id: str = "tenant-1") -> MemoryRequestScope:
    """Build one trusted runtime identity."""
    return MemoryRequestScope(
        tenant_id=tenant_id,
        agent_id="agent-1",
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        identity_provenance="runtime_derived",
    )


def _candidate(
    value: str = "metric",
    *,
    provenance: str = "explicit",
    evidence_refs: tuple[str, ...] = ("chatstorage/v1/tenant-1/agent-1/user-1/session-1/turn-1",),
) -> UserKnowledgeCandidate:
    """Build a keyed claim whose evidence can be changed independently."""
    return UserKnowledgeCandidate(
        kind="preference",
        value=value,
        normalized_key="units",
        provenance=provenance,
        evidence_refs=evidence_refs,
    )


def _upsert(event_id: str, candidate: UserKnowledgeCandidate) -> UserKnowledgeCommand:
    """Build an idempotent upsert command."""
    return UserKnowledgeCommand(event_id=event_id, candidate=candidate)


def _forget(event_id: str, knowledge_id: str, revision: int) -> UserKnowledgeCommand:
    """Build a revision-checked forget command."""
    return UserKnowledgeCommand(
        event_id=event_id,
        operation="forget",
        knowledge_id=knowledge_id,
        expected_revision=revision,
    )


async def _table_rows(path: Path, table: str) -> list[tuple[object, ...]]:
    """Read an owned SQLite table after the store commits."""
    async with aiosqlite.connect(path) as database:
        cursor = await database.execute(f"SELECT * FROM {table}")
        return await cursor.fetchall()


@pytest.mark.asyncio
async def test_forget_physically_erases_and_suppresses(tmp_path: Path) -> None:
    """Forget removes fact content while retaining only a hashed suppression identity."""
    path = tmp_path / "memory.sqlite3"
    store = UserMemoryStore(path)
    scope = _scope()
    candidate = _candidate(evidence_refs=("message:turn-1", "episode:episode-1"))
    applied = await store.upsert(_upsert("upsert-1", candidate), scope=scope)
    assert applied.knowledge_id is not None
    assert applied.revision is not None

    receipt = await store.forget(_forget("forget-1", applied.knowledge_id, applied.revision), scope=scope)

    assert receipt.status == "applied"
    assert await store.recall("metric", scope=scope) == []
    assert await store.list(scope=scope) == []
    await store.close()

    suppressions = await _table_rows(path, "user_knowledge_suppressions")
    assert len(suppressions) == 1
    assert "metric" not in repr(suppressions)
    assert "message:turn-1" not in repr(suppressions)
    database_bytes = path.read_bytes()
    assert b'"value":"metric"' not in database_bytes


@pytest.mark.asyncio
async def test_stale_replay_cannot_resurrect(tmp_path: Path) -> None:
    """Stale evidence stays suppressed, duplicate forget is idempotent, and close alone retains data."""
    path = tmp_path / "memory.sqlite3"
    scope = _scope()
    evidence = ("message:turn-1",)
    store = UserMemoryStore(path)
    applied = await store.upsert(_upsert("upsert-1", _candidate(evidence_refs=evidence)), scope=scope)
    assert applied.knowledge_id is not None
    assert applied.revision is not None
    await store.close()

    reopened = UserMemoryStore(path)
    assert [item.value for item in await reopened.recall("metric", scope=scope)] == ["metric"]
    command = _forget("forget-1", applied.knowledge_id, applied.revision)
    assert (await reopened.forget(command, scope=scope)).status == "applied"
    assert (await reopened.forget(command, scope=scope)).status == "duplicate"

    stale_inference = _candidate(provenance="inferred", evidence_refs=evidence)
    stale_explicit = _candidate(evidence_refs=evidence)
    assert (await reopened.upsert(_upsert("stale-inferred", stale_inference), scope=scope)).status == "ignored"
    assert (await reopened.upsert(_upsert("stale-explicit", stale_explicit), scope=scope)).status == "ignored"
    assert await reopened.list(scope=scope) == []
    await reopened.close()


@pytest.mark.asyncio
async def test_later_explicit_statement_lifts_marker(tmp_path: Path) -> None:
    """A new explicit same-user declaration lifts suppression without serving old content."""
    path = tmp_path / "memory.sqlite3"
    store = UserMemoryStore(path)
    scope = _scope()
    original = await store.upsert(
        _upsert("upsert-1", _candidate(evidence_refs=("message:turn-1",))),
        scope=scope,
    )
    assert original.knowledge_id is not None
    assert original.revision is not None
    await store.forget(_forget("forget-1", original.knowledge_id, original.revision), scope=scope)

    later = await store.upsert(
        _upsert("upsert-2", _candidate("SI metric", evidence_refs=("message:turn-2",))),
        scope=scope,
    )

    assert later.status == "applied"
    assert [item.value for item in await store.recall("metric", scope=scope)] == ["SI metric"]
    await store.close()
    assert await _table_rows(path, "user_knowledge_suppressions") == []


@pytest.mark.asyncio
async def test_derivative_retry_survives_restart(tmp_path: Path) -> None:
    """Source-episode invalidation remains durably queued across store restart."""
    path = tmp_path / "memory.sqlite3"
    store = UserMemoryStore(path)
    scope = _scope()
    applied = await store.upsert(
        _upsert(
            "upsert-1",
            _candidate(evidence_refs=("episode:episode-1", "episode/v1/episode-2")),
        ),
        scope=scope,
    )
    assert applied.knowledge_id is not None
    assert applied.revision is not None
    await store.forget(_forget("forget-1", applied.knowledge_id, applied.revision), scope=scope)
    await store.close()

    reopened = UserMemoryStore(path)
    await reopened.configure()
    await reopened.close()
    rows = await _table_rows(path, "user_derivative_forgets")
    assert {(row[0], row[1], row[2]) for row in rows} == {
        ("tenant-1", "episode-1", "forget-1"),
        ("tenant-1", "episode-2", "forget-1"),
    }


@pytest.mark.asyncio
async def test_tombstoned_or_foreign_tenant_evidence_unavailable(tmp_path: Path) -> None:
    """Unavailable ChatStorage evidence is ignored without content reads or suppression writes."""
    resolved_turns: list[str] = []

    async def resolve_tenant(evidence: ChatStorageEvidenceRef) -> str | None:
        resolved_turns.append(evidence.turn_id)
        if evidence.turn_id == "deleted-turn":
            return None
        if evidence.turn_id == "foreign-turn":
            return "tenant-2"
        return "tenant-1"

    path = tmp_path / "memory.sqlite3"
    store = UserMemoryStore(path, evidence_tenant_resolver=resolve_tenant)
    scope = _scope()
    deleted_ref = ChatStorageEvidenceRef(
        tenant_id="tenant-1",
        agent_name="agent-1",
        user_id="user-1",
        session_id="session-1",
        turn_id="deleted-turn",
    ).to_reference()
    foreign_stored_ref = ChatStorageEvidenceRef(
        tenant_id="tenant-1",
        agent_name="agent-1",
        user_id="user-1",
        session_id="session-1",
        turn_id="foreign-turn",
    ).to_reference()
    forged_tenant_ref = ChatStorageEvidenceRef(
        tenant_id="tenant-2",
        agent_name="agent-1",
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-3",
    ).to_reference()
    missing_tenant_ref = "chatstorage/v1/agent-1/user-1/session-1/turn-4"

    for index, reference in enumerate((deleted_ref, foreign_stored_ref, forged_tenant_ref, missing_tenant_ref)):
        receipt = await store.upsert(
            _upsert(f"upsert-{index}", _candidate(evidence_refs=(reference,))),
            scope=scope,
        )
        assert receipt.status == "ignored"

    assert resolved_turns == ["deleted-turn", "foreign-turn"]
    assert await store.list(scope=scope) == []
    await store.close()
    assert await _table_rows(path, "user_knowledge_suppressions") == []


@pytest.mark.asyncio
async def test_ignored_events_do_not_retain_forgotten_content(tmp_path: Path) -> None:
    """Events that never produced a fact keep only a digest, so a later forget leaves no claim content on disk."""
    path = tmp_path / "memory.sqlite3"
    scope = _scope()
    evidence = ("message:turn-1",)
    store = UserMemoryStore(path)
    applied = await store.upsert(_upsert("upsert-1", _candidate(evidence_refs=evidence)), scope=scope)
    assert applied.knowledge_id is not None and applied.revision is not None
    assert (
        await store.forget(_forget("forget-1", applied.knowledge_id, applied.revision), scope=scope)
    ).status == "applied"

    stale = _upsert("stale-explicit", _candidate(evidence_refs=evidence))
    assert (await store.upsert(stale, scope=scope)).status == "ignored"
    # Replay detection still works without the raw payload: same command is a duplicate, a different one conflicts.
    assert (await store.upsert(stale, scope=scope)).status == "duplicate"
    other = _upsert("stale-explicit", _candidate(evidence_refs=("message:turn-9",)))
    assert (await store.upsert(other, scope=scope)).status == "conflict"
    await store.close()

    async with aiosqlite.connect(path) as database:
        cursor = await database.execute(
            "SELECT command_payload FROM user_knowledge_events WHERE event_id = ?", ("stale-explicit",)
        )
        stored = [row[0] for row in await cursor.fetchall()]
    assert stored and all(payload.startswith("sha256:") for payload in stored)
    assert b'"value":"metric"' not in path.read_bytes()
