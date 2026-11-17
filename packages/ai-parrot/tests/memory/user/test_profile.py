"""Full-population profile and explicit recall tests using real temporary SQLite."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import pytest

from parrot.memory.agent_memory.models import MemoryRequestScope
from parrot.memory.user.models import UserKnowledge, UserKnowledgeCandidate, UserKnowledgeCommand
from parrot.memory.user.store import UserMemoryStore

_STAMP = datetime(2020, 1, 1, tzinfo=timezone.utc)


def _scope(*, user_id: str | None = "user-1", tenant_id: str = "tenant-1") -> MemoryRequestScope:
    """Build an isolated, trusted memory scope."""
    return MemoryRequestScope(
        tenant_id=tenant_id,
        agent_id="agent-1",
        user_id=user_id,
        session_id="session-1",
        turn_id="turn-1",
        identity_provenance="runtime_derived",
    )


def _knowledge(
    knowledge_id: str,
    value: str,
    *,
    scope: MemoryRequestScope,
    kind: str = "fact",
    updated: int = 0,
    status: str = "active",
    valid_from: datetime | None = None,
    expires_at: datetime | None = None,
) -> UserKnowledge:
    """Build a stable stored record with a controlled rank timestamp."""
    timestamp = _STAMP + timedelta(seconds=updated)
    return UserKnowledge(
        knowledge_id=knowledge_id,
        tenant_id=scope.tenant_id,
        agent_id=scope.agent_id,
        user_id=scope.user_id or "",
        kind=kind,
        normalized_key=knowledge_id,
        value=value,
        provenance="explicit",
        evidence_refs=(f"evidence:{knowledge_id}",),
        status=status,
        created_at=timestamp,
        updated_at=timestamp,
        confirmed_at=timestamp,
        valid_from=valid_from,
        expires_at=expires_at,
        revision=0,
    )


async def _insert(store: UserMemoryStore, knowledge: UserKnowledge) -> None:
    """Insert one prebuilt record through the store-owned SQLite connection."""
    async with store._lock:
        database = await store._configure_locked()
        await store._insert_knowledge(database, knowledge)


@pytest.mark.asyncio
async def test_profile_returns_all_active_for_unrelated_question(tmp_path: Path) -> None:
    """Unrelated queries still return active scoped knowledge."""
    scope = _scope()
    async with UserMemoryStore(tmp_path / "memory.sqlite3") as store:
        await _insert(store, _knowledge("fact", "guitar", scope=scope, updated=1))
        receipt = await store.upsert(
            UserKnowledgeCommand(
                event_id="preference",
                candidate=UserKnowledgeCandidate(
                    kind="preference",
                    value="metric units",
                    normalized_key="units",
                    provenance="explicit",
                    evidence_refs=("evidence:preference",),
                ),
            ),
            scope=scope,
        )

        profile = await store.profile(scope=scope, query="weather tomorrow", limit=20)

    assert receipt.status == "applied"
    assert {item.value for item in profile} == {"guitar", "metric units"}
    assert profile[0].kind == "preference"


@pytest.mark.asyncio
async def test_profile_orders_kind_group_then_overlap_then_recency(tmp_path: Path) -> None:
    """Kinds, overlap, timestamp and ID establish total order."""
    scope = _scope()
    async with UserMemoryStore(tmp_path / "memory.sqlite3") as store:
        records = (
            _knowledge("pref-two", "travel sun", scope=scope, kind="preference", updated=1),
            _knowledge("constraint", "travel", scope=scope, kind="constraint", updated=99),
            _knowledge("pref-z", "travel", scope=scope, kind="preference", updated=2),
            _knowledge("pref-a", "travel", scope=scope, kind="preference", updated=2),
            _knowledge("goal", "travel sun", scope=scope, kind="goal", updated=10),
            _knowledge("fact", "travel sun", scope=scope, kind="fact", updated=11),
        )
        for record in records:
            await _insert(store, record)

        profile = await store.profile(scope=scope, query="travel sun", limit=20)

    assert [item.knowledge_id for item in profile] == ["pref-two", "constraint", "pref-z", "pref-a", "fact", "goal"]


@pytest.mark.asyncio
async def test_profile_ranks_older_preference_beyond_first_page(tmp_path: Path) -> None:
    """An older preference precedes 200 newer facts."""
    scope = _scope()
    async with UserMemoryStore(tmp_path / "memory.sqlite3") as store:
        await _insert(store, _knowledge("old-preference", "use metric", scope=scope, kind="preference", updated=1))
        for index in range(200):
            await _insert(store, _knowledge(f"fact-{index:03}", "ordinary fact", scope=scope, updated=index + 100))

        profile = await store.profile(scope=scope, query="unrelated question", limit=1)

    assert [item.knowledge_id for item in profile] == ["old-preference"]


@pytest.mark.asyncio
async def test_recall_finds_unique_match_beyond_first_page(tmp_path: Path) -> None:
    """Term and short literal matches survive beyond 200 newer rows."""
    scope = _scope()
    async with UserMemoryStore(tmp_path / "memory.sqlite3") as store:
        await _insert(store, _knowledge("needle", "needle only", scope=scope, updated=1))
        await _insert(store, _knowledge("short", "SI unit", scope=scope, updated=2))
        for index in range(200):
            await _insert(store, _knowledge(f"noise-{index:03}", "ordinary noise", scope=scope, updated=index + 100))

        term_match = await store.recall("needle", scope=scope, limit=5)
        short_literal_match = await store.recall("SI", scope=scope, limit=5)

    assert [item.knowledge_id for item in term_match] == ["needle"]
    assert [item.knowledge_id for item in short_literal_match] == ["short"]


@pytest.mark.asyncio
async def test_profile_and_recall_scan_with_bounded_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Batches and winners are bounded and agree with a full-sort oracle."""
    scope = _scope()
    batch_sizes: list[int | None] = []
    original_fetchmany = aiosqlite.Cursor.fetchmany

    async def recording_fetchmany(cursor: aiosqlite.Cursor, size: int | None = None) -> list[tuple[object, ...]]:
        """Record every requested SQLite batch without changing its result."""
        batch_sizes.append(size)
        return await original_fetchmany(cursor, size)

    monkeypatch.setattr(aiosqlite.Cursor, "fetchmany", recording_fetchmany)
    async with UserMemoryStore(tmp_path / "memory.sqlite3") as store:
        for index in range(220):
            kind = "preference" if index == 0 else "fact"
            value = "common special" if index == 219 else "common"
            await _insert(store, _knowledge(f"item-{index:03}", value, scope=scope, kind=kind, updated=index))

        profile = await store.profile(scope=scope, query="common special", limit=7)
        recalled = await store.recall("common special", scope=scope, limit=7)

    assert len(profile) == len(recalled) == 7
    assert profile[0].knowledge_id == "item-000"
    assert recalled[0].knowledge_id == "item-219"
    assert batch_sizes and all(size == 100 for size in batch_sizes)


@pytest.mark.asyncio
async def test_profile_excludes_pending_superseded_and_expired(tmp_path: Path) -> None:
    """Status, validity and scope filter before ranking."""
    scope = _scope()
    other_scope = _scope(user_id="user-2")
    now = datetime.now(timezone.utc)
    async with UserMemoryStore(tmp_path / "memory.sqlite3") as store:
        await _insert(store, _knowledge("allowed", "allowed", scope=scope))
        await _insert(store, _knowledge("pending", "pending", scope=scope, status="pending"))
        await _insert(store, _knowledge("superseded", "superseded", scope=scope, status="superseded"))
        await _insert(store, _knowledge("expired", "expired", scope=scope, expires_at=now - timedelta(seconds=1)))
        await _insert(store, _knowledge("future", "future", scope=scope, valid_from=now + timedelta(seconds=1)))
        await _insert(store, _knowledge("other", "other", scope=other_scope))

        profile = await store.profile(scope=scope, query="allowed other", limit=20)
        recalled = await store.recall("allowed other", scope=scope, limit=20)

    assert [item.knowledge_id for item in profile] == ["allowed"]
    assert [item.knowledge_id for item in recalled] == ["allowed"]


@pytest.mark.asyncio
async def test_profile_requires_user_identity_and_bounded_limit(tmp_path: Path) -> None:
    """Missing identity, long queries, invalid limits and zero are handled."""
    path = tmp_path / "memory.sqlite3"
    store = UserMemoryStore(path)
    with pytest.raises(ValueError, match="missing_user_identity"):
        await store.profile(scope=_scope(user_id=None), query="x" * 3_000, limit=-1)
    with pytest.raises(ValueError, match="query exceeds"):
        await store.profile(scope=_scope(), query="x" * 2_049)
    with pytest.raises(ValueError, match="limit must be"):
        await store.profile(scope=_scope(), limit=True)

    assert await store.profile(scope=_scope(), limit=0) == []
    assert not path.exists()


@pytest.mark.asyncio
async def test_recall_matches_any_term_of_a_question(tmp_path: Path) -> None:
    """Any normalized term matches, ranked by overlap then recency."""
    scope = _scope()
    async with UserMemoryStore(tmp_path / "memory.sqlite3") as store:
        await _insert(store, _knowledge("both", "Café sun", scope=scope, updated=1))
        await _insert(store, _knowledge("cafe", "CAFÉ", scope=scope, updated=3))
        await _insert(store, _knowledge("sun", "sun", scope=scope, updated=4))
        await _insert(store, _knowledge("none", "rain", scope=scope, updated=99))

        recalled = await store.recall("Café sun", scope=scope, limit=20)

    assert [item.knowledge_id for item in recalled] == ["both", "sun", "cafe"]


@pytest.mark.asyncio
async def test_recall_blank_and_short_literal_queries_unchanged(tmp_path: Path) -> None:
    """Blank and short literal SQL semantics are preserved."""
    scope = _scope()
    async with UserMemoryStore(tmp_path / "memory.sqlite3") as store:
        await _insert(store, _knowledge("old", "old", scope=scope, updated=1))
        await _insert(store, _knowledge("new", "new", scope=scope, updated=2))
        await _insert(store, _knowledge("escaped", "literal %_ marker", scope=scope, updated=3))

        blank = await store.recall("   ", scope=scope, limit=20)
        short_literal = await store.recall("%_", scope=scope, limit=20)

    assert [item.knowledge_id for item in blank] == ["escaped", "new", "old"]
    assert [item.knowledge_id for item in short_literal] == ["escaped"]
