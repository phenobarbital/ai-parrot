"""Tests for pure guided-mode task and episodic helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock

from parrot.knowledge.manuals.models import ManualVersion, Prerequisites, ProcedureView, StepView
from parrot.memory.episodic.models import EpisodeCategory
from parrot_tools.procedures.assembly import AssembledProcedure
from parrot_tools.procedures.guided import record_completion, task_steps_for


def _procedure() -> AssembledProcedure:
    """Build a minimal assembled procedure with ordered released steps."""
    return AssembledProcedure(
        procedure=ProcedureView(procedure_id="p1", manual_id="m1", title="Assemble", kind="assembly"),
        steps=[StepView(step_id="s1", order=1, text="First"), StepView(step_id="s2", order=2, text="Second")],
        prerequisites=Prerequisites(),
        revision=ManualVersion(n=1, revision="A"),
    )


def test_guided_roundtrip() -> None:
    """Procedure labels remain procedure ids and enforce linear order."""
    steps = task_steps_for(_procedure())

    assert [item["label"] for item in steps] == ["s1", "s2"]
    assert steps[0]["depends_on_labels"] == []
    assert steps[1]["depends_on_labels"] == ["s1"]


async def test_completion_records_workflow_pattern_episode() -> None:
    """Completion uses the existing workflow category and pinned procedure metadata."""
    episodic = AsyncMock()

    await record_completion(episodic, namespace="tenant", procedure=_procedure(), user_id="u1")

    episodic.record_episode.assert_awaited_once()
    _, kwargs = episodic.record_episode.await_args
    assert kwargs["category"] is EpisodeCategory.WORKFLOW_PATTERN
    assert kwargs["metadata"] == {"procedure_id": "p1", "manual_id": "m1", "revision": "A", "user_id": "u1"}
