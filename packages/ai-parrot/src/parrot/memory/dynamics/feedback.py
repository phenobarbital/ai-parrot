"""Import historical coder feedback without inventing grades or losing retractions."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path

from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedbackStore
from parrot.memory.episodic.models import (
    FEEDBACK_IMPORT_NAMESPACE,
    EpisodeCategory,
    EpisodeOutcome,
    EpisodicMemory,
    MemoryNamespace,
)
from parrot.memory.episodic.store import EpisodicMemoryStore

_IMPORT_SCOPE_FIELDS = ("tenant_id", "agent_id", "model_id", "user_id", "session_id", "room_id", "crew_id")


def _scoped_feedback_id(feedback_id: str, namespace: MemoryNamespace) -> str:
    """Build a deterministic ID from the complete import namespace, including nulls."""
    name = json.dumps(
        ["coder-feedback:v2", [getattr(namespace, field) for field in _IMPORT_SCOPE_FIELDS], feedback_id],
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return str(uuid.uuid5(FEEDBACK_IMPORT_NAMESPACE, name))


def _feedback_episode_id(feedback_id: str, namespace: MemoryNamespace, existing: dict[str, EpisodicMemory]) -> str:
    """Reuse an exact-scope historic ID before assigning a new scoped ID."""
    for legacy_name in (feedback_id, f"coder-feedback:{feedback_id}"):
        legacy_id = str(uuid.uuid5(FEEDBACK_IMPORT_NAMESPACE, legacy_name))
        if legacy_id in existing:
            return legacy_id
    return _scoped_feedback_id(feedback_id, namespace)


async def import_feedback(
    root: Path,
    *,
    store: EpisodicMemoryStore,
    namespace: MemoryNamespace,
) -> dict[str, int]:
    """Idempotently import legacy lessons and retractions with stable IDs and provenance.

    Existing import IDs are preserved in their exact namespace. New IDs include
    all namespace dimensions so separate scopes cannot collide in write-once stores.

    Args:
        root: A checkout path used to resolve the shared SDD ledger.
        store: Episodic store receiving imported feedback records.
        namespace: Scope assigned to every imported record.

    Returns:
        Counts of newly imported, already-present, and newly tombstoned records.

    Raises:
        OSError: If the shared feedback ledger cannot be read. An outage is
            deliberately not represented as an empty import.
        RuntimeError: If concurrent writes prevent a complete compatibility scan.
            Retry the import after the writer load subsides.
    """
    feedback_store = CoderFeedbackStore.from_root(root)
    records = await asyncio.to_thread(feedback_store._read)
    retracted_ids = await asyncio.to_thread(feedback_store.retracted_feedback_ids)
    backend = store._backend
    scope = namespace.build_filter()
    limit = await backend.count(scope) + 1
    for _ in range(3):
        candidates = await backend.get_recent(scope, limit=limit)
        if len(candidates) < limit:
            break
        limit *= 2
    else:
        raise RuntimeError("Feedback import scope changed during the compatibility scan; retry the import")
    # build_filter omits null dimensions; a broad query is not exact ownership.
    existing = {
        episode.episode_id: episode
        for episode in candidates
        if all(getattr(episode, field) == getattr(namespace, field) for field in _IMPORT_SCOPE_FIELDS)
    }
    result = {"imported": 0, "skipped": 0, "retracted": 0}
    changed = False

    for recorded_at, feedback in records:
        feedback_id = feedback.feedback_id()
        episode_id = _feedback_episode_id(feedback_id, namespace, existing)
        previous = existing.get(episode_id)
        if previous is not None:
            result["skipped"] += 1
            if previous.metadata.get("coder_feedback_retracted") is True:
                await backend.update_metadata([episode_id], {"coder_feedback_retracted": False})
                changed = True
            continue

        timestamp = datetime.fromisoformat(recorded_at)
        episode = EpisodicMemory(
            episode_id=episode_id,
            created_at=timestamp,
            updated_at=timestamp,
            tenant_id=namespace.tenant_id,
            agent_id=namespace.agent_id,
            model_id=namespace.model_id,
            user_id=namespace.user_id,
            session_id=namespace.session_id,
            room_id=namespace.room_id,
            crew_id=namespace.crew_id,
            situation=f"Reviewer-confirmed coder feedback for {feedback.task_id}",
            action_taken=f"Recorded correction pattern {feedback.pattern}",
            outcome=EpisodeOutcome.PARTIAL,
            outcome_details=feedback.defect,
            lesson_learned=feedback.correction,
            category=EpisodeCategory.WORKFLOW_PATTERN,
            importance=1,
            metadata={
                "source": "coder_feedback",
                "feedback_id": feedback_id,
                "legacy_feedback_id": feedback_id,
                "recorded_at": recorded_at,
                "coder_feedback": feedback.model_dump(mode="json"),
                "coder_feedback_retracted": False,
            },
        )
        await backend.store(episode)
        existing[episode_id] = episode
        result["imported"] += 1
        changed = True

    for feedback_id in retracted_ids:
        episode_id = _feedback_episode_id(feedback_id, namespace, existing)
        previous = existing.get(episode_id)
        if previous is None or previous.metadata.get("coder_feedback_retracted") is True:
            continue
        result["retracted"] += await backend.update_metadata([episode_id], {"coder_feedback_retracted": True})
        changed = True

    if changed:
        await store._invalidate_scope_cache(namespace)

    return result
