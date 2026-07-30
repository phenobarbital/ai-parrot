"""Dream-cycle data models and JSON sidecar state persistence.

Provides the Pydantic v2 models that back the episodic-to-wiki brain
consolidation pipeline (FEAT-390):

- ``DreamState``: persisted scheduler/runner state (JSON sidecar file,
  written atomically). NOT a table in the wiki database.
- ``DreamConfig``: tunables for the dream cycle (thresholds, caps, model).
- ``DistilledKnowledge``: output contract of one distill LLM call.
- ``DreamCycleReport``: structured result of one cycle run.

This module is intentionally import-light: it only depends on
``parrot.memory.episodic.models.MemoryNamespace`` and the standard library.
No wiki or episodic-store imports belong here.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class DreamState(BaseModel):
    """Persisted scheduler/runner state (JSON sidecar, atomic write).

    Attributes:
        agent_id: Owning agent identifier.
        last_run: Watermark — created_at of the newest consolidated episode.
        next_due: Timestamp of the next scheduled dream cycle.
        interval_hours: Configured interval between cycles.
        running: Lock flag — True while a cycle is in progress.
        running_since: Timestamp the lock was acquired (stale-lock detection).
        cycles_completed: Total number of completed cycles.
        episodes_consolidated: Total number of episodes marked consolidated.
        reinforcement_counts: Maps page_id to the number of distinct cycles
            that reinforced it (used for org-promotion eligibility).
        promoted_pages: Page ids already copied into the org wiki.
    """

    agent_id: str
    last_run: datetime | None = None
    next_due: datetime | None = None
    interval_hours: float = 24.0
    running: bool = False
    running_since: datetime | None = None
    cycles_completed: int = 0
    episodes_consolidated: int = 0
    reinforcement_counts: dict[str, int] = Field(default_factory=dict)
    promoted_pages: list[str] = Field(default_factory=list)


class DreamConfig(BaseModel):
    """Tunables for the dream-cycle consolidation pipeline.

    Attributes:
        importance_threshold: Minimum episode importance to be eligible for
            consolidation (episodes with a non-empty ``lesson_learned`` are
            always eligible regardless of this threshold).
        similarity_threshold: Cosine-similarity threshold for clustering
            episodes by embedding.
        max_groups_per_cycle: Maximum number of groups distilled per cycle;
            excess groups are deferred to the next cycle.
        org_promotion_cycles: Minimum number of distinct-cycle reinforcements
            before a page is promoted to the org wiki.
        distill_model: Default LLM model used for the distill step.
        startup_jitter_seconds: Maximum random jitter applied before a
            catch-up cycle at scheduler startup.
        failure_backoff_divisor: Divisor applied to ``interval_hours`` when
            rescheduling after a store failure (backoff = interval / divisor).
    """

    importance_threshold: int = 5
    similarity_threshold: float = 0.75
    max_groups_per_cycle: int = 20
    org_promotion_cycles: int = 3
    distill_model: str = "gemini-3.1-flash-lite"
    startup_jitter_seconds: int = 60
    failure_backoff_divisor: int = 4


class DistilledKnowledge(BaseModel):
    """Output contract of one distill LLM call.

    Attributes:
        title: Short title for the distilled knowledge page.
        body: Full distilled text body.
        category: One of ``lesson | decision | concept | note``.
        confidence: Model confidence in [0, 1].
    """

    title: str
    body: str
    category: str = "lesson"
    confidence: float = 0.5


class DreamCycleReport(BaseModel):
    """Structured result of one dream cycle (logged + returned by run_now).

    Attributes:
        started_at: Cycle start timestamp.
        finished_at: Cycle completion timestamp (None if aborted early).
        episodes_collected: Number of episodes collected for this cycle.
        groups_formed: Number of clusters formed from collected episodes.
        groups_distilled: Number of groups successfully distilled.
        groups_skipped: Number of groups skipped due to LLM failure (retried
            next cycle).
        pages_written: Page ids written/updated in the brain wiki.
        pages_promoted: Page ids promoted to the org wiki this cycle.
        aborted: True if the cycle was aborted before completion.
        abort_reason: Human-readable reason for the abort, if any.
    """

    started_at: datetime
    finished_at: datetime | None = None
    episodes_collected: int = 0
    groups_formed: int = 0
    groups_distilled: int = 0
    groups_skipped: int = 0
    pages_written: list[str] = Field(default_factory=list)
    pages_promoted: list[str] = Field(default_factory=list)
    aborted: bool = False
    abort_reason: str | None = None


def save_state(state: DreamState, path: Path | str) -> None:
    """Atomically persist ``DreamState`` as JSON.

    Writes to a temporary file in the same directory then ``os.replace``s
    it over the target path, so readers never observe a partially written
    file.

    Args:
        state: The dream state to persist.
        path: Destination path of the JSON sidecar file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_state(path: Path | str, agent_id: str) -> DreamState:
    """Load ``DreamState`` from a JSON sidecar, tolerant of failures.

    Never raises: a missing file, invalid JSON, or a schema mismatch all
    result in a fresh default ``DreamState`` for ``agent_id`` (with a
    WARNING logged for the latter two cases).

    Args:
        path: Path to the JSON sidecar file.
        agent_id: Agent identifier used to build the default state when the
            file is missing or unreadable.

    Returns:
        The loaded ``DreamState``, or a fresh default one on any failure.
    """
    path = Path(path)
    if not path.exists():
        return DreamState(agent_id=agent_id)

    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return DreamState.model_validate(data)
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        logger.warning(
            "Failed to load DreamState from %s (%s); using default state.",
            path,
            exc,
        )
        return DreamState(agent_id=agent_id)
