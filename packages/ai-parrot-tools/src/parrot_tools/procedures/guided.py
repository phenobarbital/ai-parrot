"""Guided-mode helpers for procedure task plans (FEAT-601 M11)."""

from __future__ import annotations

import logging
from typing import Any

from parrot.memory.episodic.models import EpisodeCategory, EpisodeOutcome
from parrot_tools.procedures.assembly import AssembledProcedure

logger = logging.getLogger(__name__)


def task_steps_for(procedure: AssembledProcedure) -> list[dict[str, Any]]:
    """Map ordered procedure steps to a linear task-memory plan."""
    steps: list[dict[str, Any]] = []
    previous: str | None = None
    for view in procedure.steps:
        steps.append(
            {
                "label": view.step_id,
                "title": f"{view.order}. {view.text[:80]}",
                "description": view.text,
                "required": True,
                "depends_on_labels": [previous] if previous else [],
            }
        )
        previous = view.step_id
    return steps


async def record_completion(episodic: Any, *, namespace: Any, procedure: AssembledProcedure, user_id: str) -> None:
    """Record one workflow-pattern episode after a guided procedure completes."""
    if episodic is None:
        return
    await episodic.record_episode(
        namespace,
        situation=f"guided procedure {procedure.procedure.title}",
        action_taken="completed every required step",
        outcome=EpisodeOutcome.SUCCESS,
        category=EpisodeCategory.WORKFLOW_PATTERN,
        metadata={
            "procedure_id": procedure.procedure.procedure_id,
            "manual_id": procedure.procedure.manual_id,
            "revision": procedure.revision.revision,
            "user_id": user_id,
        },
    )
