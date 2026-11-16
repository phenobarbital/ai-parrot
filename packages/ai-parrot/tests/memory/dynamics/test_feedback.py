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
    return await backend.get_recent(scope, limit=await backend.count(scope))


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
        expected_id = str(uuid.uuid5(FEEDBACK_IMPORT_NAMESPACE, receipt.feedback_id))

        assert first == {"imported": 1, "skipped": 0, "retracted": 0}
        assert second == {"imported": 0, "skipped": 1, "retracted": 0}
        assert len(records) == 1
        assert records[0].episode_id == expected_id
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
