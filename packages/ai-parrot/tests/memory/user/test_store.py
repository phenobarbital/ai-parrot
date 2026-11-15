"""Behavioral acceptance tests for Independent SQLite user knowledge service."""

from pathlib import Path

import aiosqlite
import pytest

from parrot.memory.agent_memory.models import MemoryRequestScope
from parrot.memory.user.models import UserKnowledgeCandidate, UserKnowledgeCommand
from parrot.memory.user.store import UserMemoryStore


def _scope(*, user_id: str | None = "user-1", tenant_id: str = "tenant-1") -> MemoryRequestScope:
    """Build a runtime-derived isolated identity."""
    return MemoryRequestScope(
        tenant_id=tenant_id,
        agent_id="agent-1",
        user_id=user_id,
        session_id="session-1",
        turn_id="turn-1",
        identity_provenance="runtime_derived",
    )


def _candidate(
    value: str,
    *,
    key: str = "units",
    kind: str = "preference",
    provenance: str = "explicit",
    context: dict[str, str] | None = None,
) -> UserKnowledgeCandidate:
    """Build a bounded candidate with observable evidence."""
    return UserKnowledgeCandidate(
        kind=kind,
        value=value,
        normalized_key=key,
        provenance=provenance,
        context=context or {},
        evidence_refs=(f"evidence:{value}",),
    )


def _upsert(
    event_id: str,
    candidate: UserKnowledgeCandidate,
    *,
    expected_revision: int | None = None,
) -> UserKnowledgeCommand:
    """Build an upsert command."""
    return UserKnowledgeCommand(event_id=event_id, candidate=candidate, expected_revision=expected_revision)


@pytest.mark.asyncio
async def test_user_only_real_store_reopen(tmp_path: Path) -> None:
    """User-only data survives close/reopen and creates no episodic resources."""
    path = tmp_path / "memory.sqlite3"
    store = UserMemoryStore(path)
    receipt = await store.upsert(_upsert("event-1", _candidate("metric")), scope=_scope())
    assert receipt.status == "applied"
    await store.close()

    reopened = UserMemoryStore(path)
    recalled = await reopened.recall("metric", scope=_scope())
    assert [(item.value, item.status, item.revision) for item in recalled] == [("metric", "active", 0)]
    await reopened.close()

    async with aiosqlite.connect(path) as database:
        cursor = await database.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
        tables = {row[0] for row in await cursor.fetchall()}
    assert "user_knowledge" in tables
    assert "user_knowledge_events" in tables
    assert "episodes" not in tables


@pytest.mark.asyncio
async def test_explicit_correction_and_scoped_history(tmp_path: Path) -> None:
    """Explicit corrections win only inside their kind and context boundary."""
    store = UserMemoryStore(tmp_path / "memory.sqlite3")
    scope = _scope()
    original = await store.upsert(_upsert("event-1", _candidate("metric")), scope=scope)
    assert original.knowledge_id is not None

    inferred = await store.upsert(
        _upsert("event-2", _candidate("likes hiking", key="hobby", kind="fact", provenance="inferred")),
        scope=scope,
    )
    project_constraint = await store.upsert(
        _upsert(
            "event-3",
            _candidate("imperial", key="units", kind="constraint", context={"project": "apollo"}),
        ),
        scope=scope,
    )
    correction = UserKnowledgeCommand(
        event_id="event-4",
        operation="correct",
        knowledge_id=original.knowledge_id,
        expected_revision=original.revision,
        candidate=_candidate("SI metric"),
        evidence_refs=("message:correction",),
    )
    corrected = await store.correct(correction, scope=scope)

    assert inferred.status == project_constraint.status == corrected.status == "applied"
    active = await store.recall("metric", scope=scope)
    assert [(item.value, item.revision, item.supersedes_id) for item in active] == [
        ("SI metric", 1, original.knowledge_id)
    ]
    history = await store.list(scope=scope)
    by_value = {item.value: item for item in history}
    assert by_value["metric"].status == "superseded"
    assert by_value["likes hiking"].status == "pending"
    assert by_value["imperial"].status == "active"
    assert by_value["SI metric"].status == "active"
    assert "message:correction" in by_value["SI metric"].evidence_refs
    await store.close()


@pytest.mark.asyncio
async def test_duplicate_event_and_cas_conflict(tmp_path: Path) -> None:
    """Event replay is idempotent while payload reuse and stale CAS conflict."""
    store = UserMemoryStore(tmp_path / "memory.sqlite3")
    scope = _scope()
    command = _upsert("event-1", _candidate("metric"))
    applied = await store.upsert(command, scope=scope)
    duplicate = await store.upsert(command, scope=scope)
    conflicting_reuse = await store.upsert(_upsert("event-1", _candidate("imperial")), scope=scope)

    assert duplicate.status == "duplicate"
    assert duplicate.knowledge_id == applied.knowledge_id
    assert conflicting_reuse.status == "conflict"

    stale = UserKnowledgeCommand(
        event_id="event-2",
        operation="correct",
        knowledge_id=applied.knowledge_id,
        expected_revision=9,
        candidate=_candidate("SI metric"),
    )
    stale_receipt = await store.correct(stale, scope=scope)
    assert stale_receipt.status == "conflict"
    assert stale_receipt.revision == 0
    assert [item.value for item in await store.recall("metric", scope=scope)] == ["metric"]
    assert len(await store.list(scope=scope)) == 1
    await store.close()


@pytest.mark.asyncio
async def test_missing_identity_denies_query(tmp_path: Path) -> None:
    """Missing trusted user identity fails before query validation or database access."""
    path = tmp_path / "memory.sqlite3"
    store = UserMemoryStore(path)
    missing_identity = _scope(user_id=None)

    with pytest.raises(ValueError, match="missing_user_identity"):
        await store.recall("x" * 3_000, scope=missing_identity, limit=-1)
    with pytest.raises(ValueError, match="missing_user_identity"):
        await store.list(scope=missing_identity)
    with pytest.raises(ValueError, match="missing_user_identity"):
        await store.upsert(_upsert("event-1", _candidate("metric")), scope=missing_identity)
    assert not path.exists()
