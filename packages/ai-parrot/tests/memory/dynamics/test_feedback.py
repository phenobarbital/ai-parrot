"""Behavioral acceptance tests for historical coder-feedback imports."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import pytest

from parrot.flows.dev_loop.sdd_coder.models import FeedbackConfig
from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedback, CoderFeedbackStore
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.memory.dynamics.feedback import import_feedback
from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend
from parrot.memory.episodic.models import FEEDBACK_IMPORT_NAMESPACE, EpisodicMemory, MemoryNamespace
from parrot.memory.episodic.store import EpisodicMemoryStore


def _feedback() -> CoderFeedback:
    """Build a confirmed correction with stable, test-only provenance."""
    return CoderFeedback(
        task_id="TASK-1234",
        attempt_uid="attempt-1",
        backend="codex",
        model="test-model",
        source="code_review",
        pattern="missing-stable-import-id",
        files=["packages/ai-parrot/src/parrot/memory/dynamics/feedback.py"],
        defect="Historical records used random identifiers.",
        evidence="Reviewer reproduced duplicate legacy imports.",
        correction="Use the accepted UUID5 namespace and keep provenance.",
        verification="The isolated persistence test passed.",
    )


async def _episodes(backend: SQLiteEpisodeBackend, namespace: MemoryNamespace) -> list[EpisodicMemory]:
    """Read all records in the exact imported namespace."""
    scope = namespace.build_filter()
    records = await backend.get_recent(scope, limit=await backend.count(scope))
    return [
        record
        for record in records
        if all(getattr(record, key) == value for key, value in namespace.model_dump().items())
    ]


@pytest.mark.asyncio
async def test_stable_import_and_retraction_idempotency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify stable import IDs, provenance, and replayed retraction tombstones."""
    feedback_store = CoderFeedbackStore(LedgerLog(str(tmp_path / "feedback.jsonl")))
    feedback = _feedback()
    receipt = await feedback_store.record(feedback)
    monkeypatch.setattr(CoderFeedbackStore, "from_root", lambda _root: feedback_store)

    backend = SQLiteEpisodeBackend(tmp_path / "episodes.sqlite")
    await backend.configure()
    namespace = MemoryNamespace(tenant_id="tenant-a", agent_id="agent-a", model_id="test-model")
    memory_store = EpisodicMemoryStore(backend)
    try:
        first = await import_feedback(tmp_path, store=memory_store, namespace=namespace)
        second = await import_feedback(tmp_path, store=memory_store, namespace=namespace)
        records = await _episodes(backend, namespace)
        assert first == {"imported": 1, "skipped": 0, "retracted": 0}
        assert second == {"imported": 0, "skipped": 1, "retracted": 0}
        assert len(records) == 1
        assert uuid.UUID(records[0].episode_id).version == 5
        assert records[0].created_at == datetime.fromisoformat(next(feedback_store.log.iter_events())[0].ts)
        assert records[0].metadata["feedback_id"] == receipt.feedback_id
        assert records[0].metadata["coder_feedback"]["verification"] == feedback.verification

        assert await feedback_store.retract(receipt.feedback_id, "wrong attribution", "human:test") is True
        assert await import_feedback(tmp_path, store=memory_store, namespace=namespace) == {
            "imported": 0,
            "skipped": 0,
            "retracted": 1,
        }
        assert (await _episodes(backend, namespace))[0].metadata["coder_feedback_retracted"] is True
        assert await import_feedback(tmp_path, store=memory_store, namespace=namespace) == {
            "imported": 0,
            "skipped": 0,
            "retracted": 0,
        }
    finally:
        await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dimension", ["tenant_id", "agent_id", "model_id", "user_id", "session_id", "room_id", "crew_id"]
)
@pytest.mark.parametrize("narrow_first", [False, True])
async def test_imports_are_independent_in_every_namespace_dimension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dimension: str, narrow_first: bool
) -> None:
    """Imports and tombstones persist independently, including broad optional scopes."""
    feedback_store = CoderFeedbackStore(LedgerLog(str(tmp_path / "feedback.jsonl")))
    receipt = await feedback_store.record(_feedback())
    monkeypatch.setattr(CoderFeedbackStore, "from_root", lambda _root: feedback_store)
    broad = MemoryNamespace(tenant_id="tenant-a", agent_id="agent-a")
    narrow = broad.model_copy(update={dimension: 'other:scope/"value'})
    first, second = (narrow, broad) if narrow_first else (broad, narrow)
    database = tmp_path / "episodes.sqlite"
    backend = SQLiteEpisodeBackend(database)
    await backend.configure()
    try:
        store = EpisodicMemoryStore(backend)
        for namespace in (first, second):
            assert await import_feedback(tmp_path, store=store, namespace=namespace) == {
                "imported": 1,
                "skipped": 0,
                "retracted": 0,
            }
            assert len(await _episodes(backend, namespace)) == 1
        first_record = (await _episodes(backend, first))[0]
        second_record = (await _episodes(backend, second))[0]
        assert first_record.episode_id != second_record.episode_id
        assert first_record.metadata["feedback_id"] == second_record.metadata["feedback_id"] == receipt.feedback_id
    finally:
        await backend.close()

    backend = SQLiteEpisodeBackend(database)
    await backend.configure()
    try:
        store = EpisodicMemoryStore(backend)
        for namespace, original in ((first, first_record), (second, second_record)):
            assert await import_feedback(tmp_path, store=store, namespace=namespace) == {
                "imported": 0,
                "skipped": 1,
                "retracted": 0,
            }
            assert (await _episodes(backend, namespace))[0].model_dump() == original.model_dump()
        await feedback_store.retract(receipt.feedback_id, "incorrect correction", "human:test")
        assert await import_feedback(tmp_path, store=store, namespace=first) == {
            "imported": 0,
            "skipped": 0,
            "retracted": 1,
        }
        assert (await _episodes(backend, second))[0].model_dump() == second_record.model_dump()
        assert (await _episodes(backend, first))[0].metadata["coder_feedback_retracted"] is True
        assert await import_feedback(tmp_path, store=store, namespace=second) == {
            "imported": 0,
            "skipped": 0,
            "retracted": 1,
        }
        for namespace in (first, second):
            assert await import_feedback(tmp_path, store=store, namespace=namespace) == {
                "imported": 0,
                "skipped": 0,
                "retracted": 0,
            }
    finally:
        await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["", "coder-feedback:"])
@pytest.mark.parametrize("legacy_user", [None, "user-a"])
async def test_legacy_episode_is_preserved_only_in_its_exact_namespace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prefix: str, legacy_user: str | None
) -> None:
    """Both historic ID forms retain all stored data and never capture a second scope."""
    feedback_store = CoderFeedbackStore(LedgerLog(str(tmp_path / "feedback.jsonl")))
    feedback = _feedback()
    receipt = await feedback_store.record(feedback)
    monkeypatch.setattr(CoderFeedbackStore, "from_root", lambda _root: feedback_store)
    original_scope = MemoryNamespace(tenant_id="tenant-a", agent_id="agent-a", user_id=legacy_user)
    other_scope = original_scope.model_copy(update={"user_id": "user-b" if legacy_user is None else None})
    legacy_id = str(uuid.uuid5(FEEDBACK_IMPORT_NAMESPACE, prefix + receipt.feedback_id))
    timestamp = datetime.fromisoformat("2026-01-01T00:00:00+00:00")
    legacy = EpisodicMemory(
        episode_id=legacy_id,
        created_at=timestamp,
        updated_at=timestamp,
        **original_scope.model_dump(),
        situation="Existing imported lesson",
        action_taken="Existing action",
        outcome="partial",
        lesson_learned="Keep this historical content",
        metadata={"source": "coder_feedback", "feedback_id": receipt.feedback_id, "coder_feedback_retracted": False},
    )
    database = tmp_path / "episodes.sqlite"
    backend = SQLiteEpisodeBackend(database)
    await backend.configure()
    try:
        await backend.store(legacy)
    finally:
        await backend.close()
    backend = SQLiteEpisodeBackend(database)
    await backend.configure()
    try:
        store = EpisodicMemoryStore(backend)
        assert await import_feedback(tmp_path, store=store, namespace=original_scope) == {
            "imported": 0,
            "skipped": 1,
            "retracted": 0,
        }
        assert (await _episodes(backend, original_scope))[0].model_dump() == legacy.model_dump()
        assert await import_feedback(tmp_path, store=store, namespace=other_scope) == {
            "imported": 1,
            "skipped": 0,
            "retracted": 0,
        }
        assert (await _episodes(backend, other_scope))[0].episode_id != legacy_id
        await feedback_store.retract(receipt.feedback_id, "retract", "human:test")
        assert await import_feedback(tmp_path, store=store, namespace=other_scope) == {
            "imported": 0,
            "skipped": 0,
            "retracted": 1,
        }
        assert (await _episodes(backend, original_scope))[0].model_dump() == legacy.model_dump()
        assert await import_feedback(tmp_path, store=store, namespace=original_scope) == {
            "imported": 0,
            "skipped": 0,
            "retracted": 1,
        }
        assert (await _episodes(backend, original_scope))[0].episode_id == legacy_id
        # A later authoritative ledger view can restore a lesson in just one scope.
        monkeypatch.setattr(feedback_store, "_read", lambda: [(timestamp.isoformat(), feedback)])
        monkeypatch.setattr(feedback_store, "retracted_feedback_ids", set)
        assert await import_feedback(tmp_path, store=store, namespace=original_scope) == {
            "imported": 0,
            "skipped": 1,
            "retracted": 0,
        }
        restored = (await _episodes(backend, original_scope))[0]
        assert restored.model_dump(exclude={"updated_at"}) == legacy.model_dump(exclude={"updated_at"})
        assert restored.updated_at >= legacy.updated_at
        assert (await _episodes(backend, other_scope))[0].metadata["coder_feedback_retracted"] is True
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_outage_is_not_clean_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a ledger read failure remains visible to the caller."""
    feedback_store = CoderFeedbackStore(LedgerLog(str(tmp_path / "feedback.jsonl")))

    def unavailable() -> list[tuple[str, CoderFeedback]]:
        """Model an unavailable durable feedback source."""
        raise OSError("ledger unavailable")

    monkeypatch.setattr(feedback_store, "_read", unavailable)
    with pytest.raises(OSError, match="ledger unavailable"):
        await feedback_store.context("codex", "test-model", ["pkg/example.py"])


@pytest.mark.asyncio
@pytest.mark.parametrize("keep_growing", [False, True])
async def test_incomplete_scan_never_duplicates_legacy_feedback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keep_growing: bool
) -> None:
    """Concurrent inserts trigger a complete rescan or a visible failure before writes."""
    feedback_store = CoderFeedbackStore(LedgerLog(str(tmp_path / "feedback.jsonl")))
    receipt = await feedback_store.record(_feedback())
    monkeypatch.setattr(CoderFeedbackStore, "from_root", lambda _root: feedback_store)
    namespace = MemoryNamespace(tenant_id="tenant-a", agent_id="agent-a")
    legacy_id = str(uuid.uuid5(FEEDBACK_IMPORT_NAMESPACE, receipt.feedback_id))
    legacy = EpisodicMemory(
        episode_id=legacy_id,
        **namespace.model_dump(),
        created_at=datetime.fromisoformat("2020-01-01T00:00:00+00:00"),
        situation="Old imported feedback",
        action_taken="Preserve this row",
        outcome="partial",
        lesson_learned="Never duplicate existing feedback",
        metadata={"feedback_id": receipt.feedback_id, "coder_feedback_retracted": False},
    )
    backend = SQLiteEpisodeBackend(tmp_path / "episodes.sqlite")
    await backend.configure()
    try:
        await backend.store(legacy)
        original_get_recent = backend.get_recent
        calls = 0

        async def insert_before_read(namespace_filter: dict[str, str], limit: int = 10) -> list[EpisodicMemory]:
            """Insert after the count, filling each requested window under sustained load."""
            nonlocal calls
            calls += 1
            if calls == 1 or keep_growing:
                for number in range(limit):
                    await backend.store(
                        legacy.model_copy(
                            update={
                                "episode_id": f"unrelated-{calls}-{number}",
                                "created_at": datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
                                "metadata": {},
                            }
                        )
                    )
            return await original_get_recent(namespace_filter, limit=limit)

        monkeypatch.setattr(backend, "get_recent", insert_before_read)
        if keep_growing:
            with pytest.raises(RuntimeError, match="compatibility scan"):
                await import_feedback(tmp_path, store=EpisodicMemoryStore(backend), namespace=namespace)
            assert calls == 3
        else:
            assert await import_feedback(tmp_path, store=EpisodicMemoryStore(backend), namespace=namespace) == {
                "imported": 0,
                "skipped": 1,
                "retracted": 0,
            }
            assert calls == 2
        records = await original_get_recent(namespace.build_filter(), limit=100)
        imported = [record for record in records if record.metadata.get("feedback_id") == receipt.feedback_id]
        assert len(imported) == 1
        assert imported[0].model_dump() == legacy.model_dump()
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_age_warning_preserves_current_effect(tmp_path: Path) -> None:
    """Verify deprecated age filtering warns while still rendering matching feedback."""
    feedback_store = CoderFeedbackStore(LedgerLog(str(tmp_path / "feedback.jsonl")))
    await feedback_store.record(_feedback())

    with pytest.warns(DeprecationWarning, match="max_age_days"):
        context = await feedback_store.context(
            "codex",
            "test-model",
            ["packages/ai-parrot/src/parrot/memory/dynamics/feedback.py"],
            max_age_days=90,
        )
    with pytest.warns(DeprecationWarning, match="max_age_days"):
        config = FeedbackConfig(max_age_days=30)

    assert "missing-stable-import-id" in context
    assert config.max_age_days == 30


@pytest.mark.asyncio
async def test_retracted_feedback_is_not_recalled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A retraction recorded in the ledger removes the imported lesson from every recall path (spec C12)."""
    feedback_store = CoderFeedbackStore(LedgerLog(str(tmp_path / "feedback.jsonl")))
    receipt = await feedback_store.record(_feedback())
    monkeypatch.setattr(CoderFeedbackStore, "from_root", lambda _root: feedback_store)
    backend = SQLiteEpisodeBackend(tmp_path / "episodes.sqlite")
    await backend.configure()
    namespace = MemoryNamespace(tenant_id="tenant-a", agent_id="agent-a", model_id="test-model")
    memory_store = EpisodicMemoryStore(backend)
    try:
        await import_feedback(tmp_path, store=memory_store, namespace=namespace)
        before = await memory_store.recall_similar("stable import identifiers", namespace, score_threshold=0.1)
        assert [item.metadata["feedback_id"] for item in before] == [receipt.feedback_id]
        assert len(await memory_store.get_room_context(namespace)) == 1

        await feedback_store.retract(receipt.feedback_id, "wrong attribution", "human:test")
        await import_feedback(tmp_path, store=memory_store, namespace=namespace)

        assert await memory_store.recall_similar("stable import identifiers", namespace, score_threshold=0.1) == []
        assert await memory_store.get_room_context(namespace) == []
        assert await memory_store.get_user_preferences(namespace) == []
        # The record is retained (replayable); it is only withheld from recall.
        assert len(await _episodes(backend, namespace)) == 1
    finally:
        await backend.close()
