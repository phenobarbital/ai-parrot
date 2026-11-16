"""Import historical coder feedback without inventing grades or losing retractions."""

from __future__ import annotations

import asyncio
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


async def import_feedback(
    root: Path,
    *,
    store: EpisodicMemoryStore,
    namespace: MemoryNamespace,
) -> dict[str, int]:
    """Idempotently import legacy lessons and retractions with stable IDs and provenance.

    Args:
        root: A checkout path used to resolve the shared SDD ledger.
        store: Episodic store receiving imported feedback records.
        namespace: Scope assigned to every imported record.

    Returns:
        Counts of newly imported, already-present, and newly tombstoned records.

    Raises:
        OSError: If the shared feedback ledger cannot be read. An outage is
            deliberately not represented as an empty import.
    """
    feedback_store = CoderFeedbackStore.from_root(root)
    records = await asyncio.to_thread(feedback_store._read)
    retracted_ids = await asyncio.to_thread(feedback_store.retracted_feedback_ids)
    backend = store._backend
    scope = namespace.build_filter()
    existing_count = await backend.count(scope)
    existing = {episode.episode_id: episode for episode in await backend.get_recent(scope, limit=existing_count)}
    result = {"imported": 0, "skipped": 0, "retracted": 0}
    changed = False

    for recorded_at, feedback in records:
        feedback_id = feedback.feedback_id()
        episode_id = str(uuid.uuid5(FEEDBACK_IMPORT_NAMESPACE, feedback_id))
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
        episode_id = str(uuid.uuid5(FEEDBACK_IMPORT_NAMESPACE, feedback_id))
        previous = existing.get(episode_id)
        if previous is None or previous.metadata.get("coder_feedback_retracted") is True:
            continue
        result["retracted"] += await backend.update_metadata([episode_id], {"coder_feedback_retracted": True})
        changed = True

    if changed:
        await store._invalidate_scope_cache(namespace)

    return result
