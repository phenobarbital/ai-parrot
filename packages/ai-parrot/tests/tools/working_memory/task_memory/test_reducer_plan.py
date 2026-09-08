"""Unit tests for the pure task-state reducer (FEAT-538 / TASK-2973).

Three required cases from the task's Test Specification:

- ``test_replay`` — identical sequences reproduce identical state, with
  no clock, randomness or I/O involved.
- ``test_plan_validation`` — invalid plan batches fail; completed
  criteria cannot silently change; superseded dependencies never count
  as complete.
- ``test_completion`` — exhausted partial plans stay active; transitive
  reopen and hint staleness propagate; terminal task rules hold.

Each is a group of focused functions plus an aggregate carrying the
required name, so a failure names the invariant that broke.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence, Tuple

import pytest
from parrot.tools.working_memory.task_memory.models import (
    Actor,
    CompletionPolicy,
    CompletionSource,
    DecisionPayload,
    EventType,
    JournalEvent,
    PlanConstraintSpec,
    PlanStepPatch,
    PlanStepSpec,
    PlanUpdatePayload,
    PlanValidationError,
    ReducerError,
    ResumeHintPayload,
    StepPayload,
    StepStatus,
    TaskLifecyclePayload,
    TaskScope,
    TaskState,
    TaskStatus,
)
from parrot.tools.working_memory.task_memory.reducer import (
    PLAN_INCOMPLETE,
    REDUCER_VERSION,
    UPSTREAM_REOPENED,
    reduce,
    replay,
    validate_plan_graph,
)

SCOPE = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")
OTHER_SCOPE = TaskScope(chatbot_id="bot-a", user_id="user-2", session_id="sess-1")

#: A fixed instant. The reducer must never read a clock, so every
#: timestamp in these tests is supplied by the events themselves.
T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class _Journal:
    """Builds a deterministic, correctly sequenced journal.

    Sequence numbers and timestamps are assigned by this helper rather
    than by the reducer, which is the point: the reducer's output must be
    a function of its input alone.
    """

    def __init__(self, task_id: str = "t-1") -> None:
        """Initialize an empty journal.

        Args:
            task_id: The task every event belongs to.
        """
        self.task_id = task_id
        self._seq = 0
        self.events: List[JournalEvent] = []

    def add(self, event_type: EventType, payload: object, **kwargs: object) -> JournalEvent:
        """Append an event with the next sequence and a deterministic time.

        Args:
            event_type: The event type.
            payload: Its typed payload.
            **kwargs: Extra :class:`JournalEvent` fields.

        Returns:
            The appended event.
        """
        self._seq += 1
        event = JournalEvent(
            event_id=f"{self.task_id}-e{self._seq}",
            task_id=self.task_id,
            seq=self._seq,
            occurred_at=T0 + timedelta(seconds=self._seq),
            event_type=event_type,
            payload=payload,  # type: ignore[arg-type]
            **kwargs,  # type: ignore[arg-type]
        )
        self.events.append(event)
        return event

    def start(self, goal: str = "Produce the quarterly report") -> "_Journal":
        """Append the ``task_started`` event.

        Args:
            goal: The task's goal.

        Returns:
            This journal, for chaining.
        """
        self.add(EventType.TASK_STARTED, TaskLifecyclePayload(status=TaskStatus.ACTIVE, goal=goal))
        return self

    def plan(self, **kwargs: object) -> "_Journal":
        """Append a ``plan_updated`` event.

        Args:
            **kwargs: :class:`PlanUpdatePayload` fields.

        Returns:
            This journal, for chaining.
        """
        self.add(EventType.PLAN_UPDATED, PlanUpdatePayload(**kwargs))  # type: ignore[arg-type]
        return self

    def step(self, event_type: EventType, step_id: str, **kwargs: object) -> "_Journal":
        """Append a step transition.

        Args:
            event_type: Which step event.
            step_id: The step it targets.
            **kwargs: Extra :class:`StepPayload` fields.

        Returns:
            This journal, for chaining.
        """
        target = {
            EventType.STEP_STARTED: StepStatus.RUNNING,
            EventType.STEP_BLOCKED: StepStatus.BLOCKED,
            EventType.STEP_COMPLETED: StepStatus.COMPLETED,
            EventType.STEP_FAILED: StepStatus.FAILED,
            EventType.STEP_REOPENED: StepStatus.PENDING,
            EventType.STEP_CANCELLED: StepStatus.CANCELLED,
        }[event_type]
        kwargs.setdefault("status", target)
        self.add(event_type, StepPayload(step_id=step_id, **kwargs))  # type: ignore[arg-type]
        return self

    def lifecycle(self, event_type: EventType, status: TaskStatus, **kwargs: object) -> "_Journal":
        """Append a task-level transition.

        Args:
            event_type: Which lifecycle event.
            status: The status it moves to.
            **kwargs: Extra payload fields.

        Returns:
            This journal, for chaining.
        """
        self.add(event_type, TaskLifecyclePayload(status=status, **kwargs))  # type: ignore[arg-type]
        return self

    def build(self, scope: TaskScope = SCOPE) -> TaskState:
        """Replay the whole journal.

        Args:
            scope: Scope to stamp on the projection.

        Returns:
            The final projection.
        """
        state = replay(self.events, scope=scope)
        assert state is not None
        return state


def _three_step_plan() -> _Journal:
    """Return a journal with a started task and a load → clean → report plan."""
    return (
        _Journal()
        .start()
        .plan(
            added_steps=(
                PlanStepSpec(step_id="s-load", title="Load raw data"),
                PlanStepSpec(step_id="s-clean", title="Clean data", depends_on=("s-load",)),
                PlanStepSpec(step_id="s-report", title="Write report", depends_on=("s-clean",)),
            ),
            added_constraints=(PlanConstraintSpec(constraint_id="c-1", text="Never mutate the source"),),
        )
    )


# ─────────────────────────────────────────────────────────────
# Replay
# ─────────────────────────────────────────────────────────────


def test_replay_is_deterministic() -> None:
    """The same journal replayed twice yields byte-identical state."""
    journal = _three_step_plan().step(EventType.STEP_COMPLETED, "s-load", note="done")

    first = journal.build()
    second = journal.build()
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()


def test_replay_uses_no_clock_or_randomness() -> None:
    """Reduction reads no wall clock and mints no identifiers.

    Checked structurally, by parsing ``reducer.py``, rather than by
    monkeypatching: Pydantic captures ``default_factory`` callables at
    class-definition time, so patching ``models.utc_now`` would not
    actually intercept a default and the test would pass while proving
    nothing.

    If the reducer read a clock or minted an id, replay would stop being
    reproducible and a projection rebuilt after a restart would silently
    disagree with the one it replaced.
    """
    import ast
    import importlib
    from pathlib import Path

    module = importlib.import_module("parrot.tools.working_memory.task_memory.reducer")
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))

    forbidden = {"utc_now", "new_id", "uuid4", "uuid1", "time", "now", "today", "random"}
    called: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name in forbidden:
                called.add(name)
    assert called == set(), f"reducer.py calls non-deterministic function(s): {sorted(called)}"

    imported: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {
        "random",
        "uuid",
        "time",
        "datetime",
        "os",
        "pathlib",
    }, f"reducer.py imports a non-deterministic or I/O module: {sorted(imported)}"

    # And observably: every timestamp came from the events, not from "now".
    state = _three_step_plan().build()
    assert state.created_at == T0 + timedelta(seconds=1)
    assert state.updated_at == T0 + timedelta(seconds=2)


def test_replay_ignores_already_applied_sequences() -> None:
    """A re-delivered event returns the *same* state object, unchanged."""
    journal = _three_step_plan()
    state = journal.build()

    replayed = reduce(state, journal.events[-1])
    assert replayed is state, "an already-applied event must change nothing at all"

    older = reduce(state, journal.events[0])
    assert older is state


def test_replay_rejects_forward_sequence_gaps() -> None:
    """A skipped sequence raises: a projection must never skip an event."""
    journal = _three_step_plan()
    state = journal.build()

    gapped = JournalEvent(
        task_id="t-1",
        seq=state.last_event_seq + 2,
        occurred_at=T0,
        event_type=EventType.TASK_PAUSED,
        payload=TaskLifecyclePayload(status=TaskStatus.PAUSED),
    )
    with pytest.raises(ReducerError, match="sequence gap"):
        reduce(state, gapped)


def test_replay_requires_a_task_started_first() -> None:
    """Only ``task_started`` may begin a task, and only at sequence 1."""
    stray = JournalEvent(
        task_id="t-1",
        seq=1,
        occurred_at=T0,
        event_type=EventType.TASK_PAUSED,
        payload=TaskLifecyclePayload(status=TaskStatus.PAUSED),
    )
    with pytest.raises(ReducerError, match="first event must be task_started"):
        reduce(None, stray, scope=SCOPE)

    late_start = JournalEvent(
        task_id="t-1",
        seq=4,
        occurred_at=T0,
        event_type=EventType.TASK_STARTED,
        payload=TaskLifecyclePayload(status=TaskStatus.ACTIVE, goal="g"),
    )
    with pytest.raises(ReducerError, match="sequence 1"):
        reduce(None, late_start, scope=SCOPE)

    goalless = JournalEvent(
        task_id="t-1",
        seq=1,
        occurred_at=T0,
        event_type=EventType.TASK_STARTED,
        payload=TaskLifecyclePayload(status=TaskStatus.ACTIVE),
    )
    with pytest.raises(ReducerError, match="must carry the task's goal"):
        reduce(None, goalless, scope=SCOPE)


def test_replay_requires_a_scope_to_begin() -> None:
    """A new projection cannot be attributed without its trusted scope."""
    start = JournalEvent(
        task_id="t-1",
        seq=1,
        occurred_at=T0,
        event_type=EventType.TASK_STARTED,
        payload=TaskLifecyclePayload(status=TaskStatus.ACTIVE, goal="g"),
    )
    with pytest.raises(ReducerError, match="requires the trusted scope"):
        reduce(None, start)

    assert reduce(None, start, scope=SCOPE).scope.matches(SCOPE)


def test_replay_rejects_a_duplicate_task_start() -> None:
    """A second ``task_started`` is malformed, not a restart."""
    journal = _Journal().start()
    state = journal.build()
    second = JournalEvent(
        task_id="t-1",
        seq=2,
        occurred_at=T0,
        event_type=EventType.TASK_STARTED,
        payload=TaskLifecyclePayload(status=TaskStatus.ACTIVE, goal="again"),
    )
    with pytest.raises(ReducerError, match="only be the first event"):
        reduce(state, second)


def test_replay_rejects_a_foreign_task_id() -> None:
    """An event for another task never lands in this projection."""
    state = _Journal().start().build()
    foreign = JournalEvent(
        task_id="t-999",
        seq=2,
        occurred_at=T0,
        event_type=EventType.TASK_PAUSED,
        payload=TaskLifecyclePayload(status=TaskStatus.PAUSED),
    )
    with pytest.raises(ReducerError, match="belongs to task"):
        reduce(state, foreign)


def test_replay_rejects_an_unknown_reducer_version() -> None:
    """A projection from a newer reducer is rejected, not guessed at."""
    state = _Journal().start().build()
    future = state.model_copy(update={"reducer_version": REDUCER_VERSION + 1})
    with pytest.raises(ReducerError, match="reducer version"):
        reduce(future, _Journal().start().events[0].model_copy(update={"seq": 2}))


def test_replay_rejects_a_payload_contradicting_its_event_type() -> None:
    """A payload whose status disagrees with its event type never wins."""
    state = _Journal().start().build()
    lying = JournalEvent(
        task_id="t-1",
        seq=2,
        occurred_at=T0,
        event_type=EventType.TASK_PAUSED,
        payload=TaskLifecyclePayload(status=TaskStatus.COMPLETED),
    )
    with pytest.raises(ReducerError, match="must carry status 'paused'"):
        reduce(state, lying)


def test_replay_rejects_unhandled_event_families() -> None:
    """An unhandled event raises rather than silently changing nothing.

    The tool-call and artifact families are registered by TASK-2974. Until
    then they must fail loudly: an event that quietly leaves the
    projection unchanged is how a projection drifts from its journal.
    """
    from parrot.tools.working_memory.task_memory.models import CallOutcome, ToolCallPayload

    state = _Journal().start().build()
    tool_event = JournalEvent(
        task_id="t-1",
        seq=2,
        occurred_at=T0,
        event_type=EventType.TOOL_SUCCEEDED,
        payload=ToolCallPayload(call_id="c1", tool_name="wm_store", outcome=CallOutcome.SUCCESS),
    )
    with pytest.raises(ReducerError, match="no reducer handler"):
        reduce(state, tool_event)


def test_replay_advances_revision_and_sequence_monotonically() -> None:
    """Revision advances per state-changing event; plan_revision only on plan changes."""
    journal = _three_step_plan()
    state = journal.build()
    assert state.revision == 2  # task_started + plan_updated
    assert state.plan_revision == 1
    assert state.last_event_seq == 2

    journal.step(EventType.STEP_STARTED, "s-load")
    state = journal.build()
    assert state.revision == 3
    assert state.plan_revision == 1, "a step transition is not a plan change"
    assert state.last_event_seq == 3


def test_replay_of_empty_journal_is_none() -> None:
    """Replaying nothing yields nothing, rather than an empty task."""
    assert replay([], scope=SCOPE) is None


def test_replay() -> None:
    """Required aggregate case: identical sequences reproduce identical state."""
    test_replay_is_deterministic()
    test_replay_uses_no_clock_or_randomness()
    test_replay_ignores_already_applied_sequences()
    test_replay_rejects_forward_sequence_gaps()
    test_replay_requires_a_task_started_first()
    test_replay_requires_a_scope_to_begin()
    test_replay_rejects_a_duplicate_task_start()
    test_replay_rejects_a_foreign_task_id()
    test_replay_rejects_a_payload_contradicting_its_event_type()
    test_replay_rejects_unhandled_event_families()
    test_replay_advances_revision_and_sequence_monotonically()
    test_replay_of_empty_journal_is_none()


# ─────────────────────────────────────────────────────────────
# Plan validation
# ─────────────────────────────────────────────────────────────


def test_plan_validation_rejects_cycles() -> None:
    """A dependency cycle is rejected, including one formed only by a batch."""
    journal = _Journal().start()
    with pytest.raises(PlanValidationError, match="cycle"):
        journal.plan(
            added_steps=(
                PlanStepSpec(step_id="a", title="A", depends_on=("b",)),
                PlanStepSpec(step_id="b", title="B", depends_on=("a",)),
            )
        ).build()

    # A cycle closed by a *later* revision is caught just the same.
    good = (
        _Journal()
        .start()
        .plan(
            added_steps=(
                PlanStepSpec(step_id="a", title="A"),
                PlanStepSpec(step_id="b", title="B", depends_on=("a",)),
            )
        )
    )
    good.build()
    with pytest.raises(PlanValidationError, match="cycle"):
        good.plan(updated_steps=(PlanStepPatch(step_id="a", depends_on=("b",)),)).build()

    # Longer cycles too.
    with pytest.raises(PlanValidationError, match="cycle"):
        validate_plan_graph(
            _three_step_plan().build().steps[:0]
            + tuple(
                __import__("parrot.tools.working_memory.task_memory.models", fromlist=["TaskStep"]).TaskStep(
                    step_id=sid, title=sid, depends_on=(dep,)
                )
                for sid, dep in (("x", "y"), ("y", "z"), ("z", "x"))
            )
        )


def test_plan_validation_rejects_missing_dependencies() -> None:
    """A dependency naming a step that does not exist is rejected."""
    with pytest.raises(PlanValidationError, match="unknown steps"):
        _Journal().start().plan(added_steps=(PlanStepSpec(step_id="a", title="A", depends_on=("ghost",)),)).build()


def test_plan_validation_rejects_duplicate_ids() -> None:
    """Step identities are immutable and unique."""
    journal = _Journal().start().plan(added_steps=(PlanStepSpec(step_id="a", title="A"),))
    journal.build()
    with pytest.raises(PlanValidationError, match="already exists"):
        journal.plan(added_steps=(PlanStepSpec(step_id="a", title="A again"),)).build()


def test_plan_validation_rejects_unknown_targets() -> None:
    """Patching, superseding or rewording something absent is malformed."""
    base = _three_step_plan()
    base.build()

    with pytest.raises(ReducerError, match="patches unknown step"):
        _three_step_plan().plan(updated_steps=(PlanStepPatch(step_id="ghost", title="x"),)).build()
    with pytest.raises(ReducerError, match="supersedes unknown step"):
        _three_step_plan().plan(superseded_step_ids=("ghost",)).build()
    with pytest.raises(ReducerError, match="rewords unknown constraint"):
        _three_step_plan().plan(updated_constraints=(PlanConstraintSpec(constraint_id="ghost", text="x"),)).build()
    with pytest.raises(ReducerError, match="deactivates unknown constraint"):
        _three_step_plan().plan(deactivated_constraint_ids=("ghost",)).build()


def test_plan_validation_completed_criteria_cannot_change_in_place() -> None:
    """A completed step's criteria and inputs are frozen until it reopens.

    Silently rewriting what a completed step was supposed to prove would
    retroactively change the meaning of evidence already accepted.
    """
    journal = _three_step_plan().step(EventType.STEP_COMPLETED, "s-load", note="done")
    journal.build()

    with pytest.raises(PlanValidationError, match="reopen it before changing its"):
        _three_step_plan().step(EventType.STEP_COMPLETED, "s-load", note="done").plan(
            updated_steps=(PlanStepPatch(step_id="s-load", completion_policy=CompletionPolicy()),)
        ).build()

    with pytest.raises(PlanValidationError, match="reopen it before changing its"):
        _three_step_plan().step(EventType.STEP_COMPLETED, "s-load", note="done").plan(
            updated_steps=(PlanStepPatch(step_id="s-load", depends_on=()),)
        ).build()

    # A cosmetic change is still allowed — it changes no criterion.
    relabelled = (
        _three_step_plan()
        .step(EventType.STEP_COMPLETED, "s-load", note="done")
        .plan(updated_steps=(PlanStepPatch(step_id="s-load", title="Load raw data (v2)"),))
        .build()
    )
    assert relabelled.steps_by_id["s-load"].title == "Load raw data (v2)"
    assert relabelled.steps_by_id["s-load"].status is StepStatus.COMPLETED


def test_plan_validation_supersession_retains_history() -> None:
    """A superseded step keeps its evidence and never satisfies readiness."""
    journal = (
        _three_step_plan().step(EventType.STEP_COMPLETED, "s-load", note="done").plan(superseded_step_ids=("s-load",))
    )
    state = journal.build()

    retired = state.steps_by_id["s-load"]
    assert retired.status is StepStatus.SUPERSEDED
    assert retired.completion_note == "done", "supersession retains history"

    # s-clean depends on the superseded step and is therefore NOT ready.
    assert "s-clean" not in state.ready_step_ids
    assert state.ready_step_ids == ()


def test_plan_validation_superseded_steps_accept_no_transitions() -> None:
    """A retired step is retired: it cannot be started or completed again."""
    journal = _three_step_plan().plan(superseded_step_ids=("s-load",))
    journal.build()
    with pytest.raises(ReducerError, match="superseded and accepts no further"):
        _three_step_plan().plan(superseded_step_ids=("s-load",)).step(EventType.STEP_STARTED, "s-load").build()


def test_plan_validation_constraints_are_retained_not_deleted() -> None:
    """Deactivating a constraint retires it; it is never removed."""
    journal = _three_step_plan().plan(deactivated_constraint_ids=("c-1",))
    state = journal.build()

    assert len(state.constraints) == 1
    assert state.constraints[0].active is False
    assert state.active_constraints == ()

    reworded = (
        _three_step_plan()
        .plan(updated_constraints=(PlanConstraintSpec(constraint_id="c-1", text="Read-only source"),))
        .build()
    )
    assert reworded.active_constraints[0].text == "Read-only source"


def test_plan_validation_rejects_events_naming_unknown_steps() -> None:
    """A step event for a step the plan never had is malformed."""
    with pytest.raises(ReducerError, match="unknown step"):
        _three_step_plan().step(EventType.STEP_STARTED, "ghost").build()

    hinting = _three_step_plan()
    hinting.add(EventType.RESUME_HINT_UPDATED, ResumeHintPayload(text="do it", step_id="ghost"))
    with pytest.raises(ReducerError, match="unknown step"):
        hinting.build()


def test_plan_validation_records_definitions_so_replay_rebuilds_the_plan() -> None:
    """Replay from an empty projection reconstructs the whole plan."""
    journal = _three_step_plan()
    state = journal.build()

    assert [s.step_id for s in state.steps] == ["s-load", "s-clean", "s-report"]
    assert state.steps_by_id["s-clean"].depends_on == ("s-load",)
    assert state.steps_by_id["s-clean"].title == "Clean data"
    assert state.active_constraints[0].text == "Never mutate the source"
    assert state.steps_by_id["s-load"].created_revision == 2


def test_plan_validation() -> None:
    """Required aggregate case: invalid plan batches fail without mutating state."""
    test_plan_validation_rejects_cycles()
    test_plan_validation_rejects_missing_dependencies()
    test_plan_validation_rejects_duplicate_ids()
    test_plan_validation_rejects_unknown_targets()
    test_plan_validation_completed_criteria_cannot_change_in_place()
    test_plan_validation_supersession_retains_history()
    test_plan_validation_superseded_steps_accept_no_transitions()
    test_plan_validation_constraints_are_retained_not_deleted()
    test_plan_validation_records_definitions_so_replay_rebuilds_the_plan()


# ─────────────────────────────────────────────────────────────
# Completion, reopen and terminal rules
# ─────────────────────────────────────────────────────────────


def _complete_all(journal: _Journal) -> _Journal:
    """Complete every step of the three-step plan in dependency order.

    Args:
        journal: The journal to extend.

    Returns:
        The same journal, for chaining.
    """
    for step_id in ("s-load", "s-clean", "s-report"):
        journal.step(
            EventType.STEP_COMPLETED,
            step_id,
            note="done",
            completion_source=CompletionSource.AGENT_ASSERTED,
        )
    return journal


def test_completion_requires_plan_complete() -> None:
    """An exhausted partial plan stays active and reports plan_incomplete."""
    journal = _complete_all(_three_step_plan())
    state = journal.build()

    assert state.status is TaskStatus.ACTIVE
    assert state.can_complete is False, "the plan was never declared complete"

    with pytest.raises(ReducerError, match=PLAN_INCOMPLETE):
        _complete_all(_three_step_plan()).lifecycle(EventType.TASK_COMPLETED, TaskStatus.COMPLETED).build()


def test_completion_requires_every_required_step() -> None:
    """Declaring the plan complete is not enough while required work remains."""
    journal = _three_step_plan().plan(plan_complete=True)
    journal.step(EventType.STEP_COMPLETED, "s-load", note="done")
    state = journal.build()
    assert state.plan_complete is True
    assert state.can_complete is False

    with pytest.raises(ReducerError, match="required steps are not all completed"):
        journal.lifecycle(EventType.TASK_COMPLETED, TaskStatus.COMPLETED).build()


def test_completion_succeeds_when_the_guard_passes() -> None:
    """With a complete plan and every required step done, the task completes."""
    journal = _complete_all(_three_step_plan().plan(plan_complete=True))
    assert journal.build().can_complete is True

    completed = journal.lifecycle(EventType.TASK_COMPLETED, TaskStatus.COMPLETED).build()
    assert completed.status is TaskStatus.COMPLETED
    assert completed.terminal_at == T0 + timedelta(seconds=len(journal.events))


def test_completion_ignores_optional_and_superseded_steps() -> None:
    """Only required, non-superseded steps gate completion."""
    journal = (
        _Journal()
        .start()
        .plan(
            added_steps=(
                PlanStepSpec(step_id="a", title="A"),
                PlanStepSpec(step_id="b", title="B", required=False),
                PlanStepSpec(step_id="c", title="C"),
            ),
            plan_complete=True,
        )
        .plan(superseded_step_ids=("c",))
        .step(EventType.STEP_COMPLETED, "a", note="done")
    )
    state = journal.build()
    assert state.can_complete is True, "an optional pending step and a retired one do not block"
    assert journal.lifecycle(EventType.TASK_COMPLETED, TaskStatus.COMPLETED).build().status is TaskStatus.COMPLETED


def test_completion_terminal_task_rejects_ordinary_mutation() -> None:
    """A finished task accepts no further ordinary work."""
    journal = _complete_all(_three_step_plan().plan(plan_complete=True)).lifecycle(
        EventType.TASK_COMPLETED, TaskStatus.COMPLETED
    )
    journal.build()

    for event_type, payload in (
        (EventType.STEP_STARTED, StepPayload(step_id="s-load", status=StepStatus.RUNNING)),
        (EventType.PLAN_UPDATED, PlanUpdatePayload(added_steps=(PlanStepSpec(step_id="z", title="Z"),))),
        (EventType.RESUME_HINT_UPDATED, ResumeHintPayload(text="carry on")),
        (EventType.DECISION_RECORDED, DecisionPayload(decision_id="d-1", text="x")),
    ):
        extended = _complete_all(_three_step_plan().plan(plan_complete=True)).lifecycle(
            EventType.TASK_COMPLETED, TaskStatus.COMPLETED
        )
        with pytest.raises(ReducerError, match="accepts no ordinary mutation"):
            extended.add(event_type, payload)
            extended.build()


def test_completion_reopen_blocks_transitive_dependents() -> None:
    """Reopening a step blocks everything downstream with upstream_reopened."""
    journal = _complete_all(_three_step_plan())
    state = journal.build()
    assert all(s.status is StepStatus.COMPLETED for s in state.steps)

    journal.step(EventType.STEP_REOPENED, "s-load")
    state = journal.build()

    assert state.steps_by_id["s-load"].status is StepStatus.PENDING
    for downstream in ("s-clean", "s-report"):
        step = state.steps_by_id[downstream]
        assert step.status is StepStatus.BLOCKED, f"{downstream} must block transitively"
        assert step.blocked_reason == UPSTREAM_REOPENED

    # A blocked dependent is not ready merely because upstream completes.
    journal.step(EventType.STEP_COMPLETED, "s-load", note="redone")
    state = journal.build()
    assert state.steps_by_id["s-clean"].status is StepStatus.BLOCKED
    assert state.ready_step_ids == (), "readiness returns only after explicit revalidation"

    # Explicit revalidation is what restores it.
    journal.step(EventType.STEP_REOPENED, "s-clean")
    state = journal.build()
    assert state.steps_by_id["s-clean"].status is StepStatus.PENDING
    assert "s-clean" in state.ready_step_ids


def test_completion_reopen_retains_previous_evidence() -> None:
    """Reopening asks for revalidation; it does not erase history."""
    from parrot.tools.working_memory.task_memory.models import EvidenceRef

    ref = EvidenceRef(artifact_id="art-1", version=2)
    journal = _three_step_plan().step(
        EventType.STEP_COMPLETED,
        "s-load",
        note="done",
        evidence_refs=(ref,),
        completion_source=CompletionSource.VALIDATED,
    )
    state = journal.build()
    assert state.steps_by_id["s-load"].evidence_refs == (ref,)
    assert state.steps_by_id["s-load"].completion_source is CompletionSource.VALIDATED

    journal.step(EventType.STEP_REOPENED, "s-load")
    state = journal.build()
    reopened = state.steps_by_id["s-load"]
    assert reopened.evidence_refs == (ref,), "previous evidence is retained"
    assert reopened.completion_source is None, "but it no longer counts as completed"
    assert reopened.completion_note is None


def test_completion_evidence_accumulates_across_attempts() -> None:
    """Completing again adds evidence rather than discarding what was proved."""
    from parrot.tools.working_memory.task_memory.models import EvidenceRef

    first = EvidenceRef(artifact_id="art-1", version=1)
    second = EvidenceRef(artifact_id="art-2", version=1)
    journal = (
        _three_step_plan()
        .step(EventType.STEP_COMPLETED, "s-load", note="a", evidence_refs=(first,))
        .step(EventType.STEP_REOPENED, "s-load")
        .step(EventType.STEP_COMPLETED, "s-load", note="b", evidence_refs=(second,))
    )
    state = journal.build()
    assert state.steps_by_id["s-load"].evidence_refs == (first, second)


def test_completion_hint_goes_stale_from_its_neighbourhood() -> None:
    """A later event touching the hint's step or its neighbours marks it stale."""
    journal = _three_step_plan()
    journal.add(EventType.RESUME_HINT_UPDATED, ResumeHintPayload(text="clean next", step_id="s-clean"))
    state = journal.build()
    assert state.resume_hint is not None
    assert state.resume_hint.stale is False

    # Touching an upstream dependency invalidates the advice.
    journal.step(EventType.STEP_COMPLETED, "s-load", note="done")
    state = journal.build()
    assert state.resume_hint is not None and state.resume_hint.stale is True


def test_completion_hint_survives_unrelated_events() -> None:
    """A hint is not marked stale by work in a different part of the plan."""
    journal = (
        _Journal()
        .start()
        .plan(
            added_steps=(
                PlanStepSpec(step_id="a", title="A"),
                PlanStepSpec(step_id="unrelated", title="Unrelated"),
            )
        )
    )
    journal.add(EventType.RESUME_HINT_UPDATED, ResumeHintPayload(text="do a", step_id="a"))
    journal.step(EventType.STEP_COMPLETED, "unrelated", note="done")
    state = journal.build()
    assert state.resume_hint is not None and state.resume_hint.stale is False


def test_completion_a_new_hint_is_never_born_stale() -> None:
    """Staleness is derived from what happens *after* a hint."""
    journal = _three_step_plan().step(EventType.STEP_COMPLETED, "s-load", note="done")
    journal.add(EventType.RESUME_HINT_UPDATED, ResumeHintPayload(text="clean next", step_id="s-clean"))
    state = journal.build()
    assert state.resume_hint is not None and state.resume_hint.stale is False


def test_completion_decisions_record_and_retire() -> None:
    """Decisions accumulate; retiring one keeps it for history."""
    journal = _three_step_plan()
    journal.add(
        EventType.DECISION_RECORDED,
        DecisionPayload(decision_id="d-1", text="use parquet", reason="faster"),
        actor=Actor.AGENT,
    )
    state = journal.build()
    assert state.active_decisions[0].text == "use parquet"
    assert state.active_decisions[0].actor is Actor.AGENT

    journal.add(
        EventType.DECISION_RECORDED,
        DecisionPayload(decision_id="d-1", text="use parquet", active=False),
    )
    state = journal.build()
    assert len(state.decisions) == 1
    assert state.decisions[0].active is False
    assert state.active_decisions == ()

    retiring = _three_step_plan()
    retiring.add(EventType.DECISION_RECORDED, DecisionPayload(decision_id="ghost", text="x", active=False))
    with pytest.raises(ReducerError, match="retires unknown decision"):
        retiring.build()


def test_completion_pause_resume_clears_terminal_marker() -> None:
    """Non-terminal transitions leave no stale terminal timestamp behind."""
    journal = (
        _three_step_plan()
        .lifecycle(EventType.TASK_PAUSED, TaskStatus.PAUSED, reason="inactivity")
        .lifecycle(EventType.TASK_RESUMED, TaskStatus.ACTIVE)
    )
    state = journal.build()
    assert state.status is TaskStatus.ACTIVE
    assert state.terminal_at is None


def test_completion_failure_does_not_auto_fail_the_task() -> None:
    """A failed step leaves the task active — failure is not automatic escalation."""
    journal = _three_step_plan().step(EventType.STEP_FAILED, "s-load", reason="source unreachable")
    state = journal.build()
    assert state.status is TaskStatus.ACTIVE
    assert state.steps_by_id["s-load"].status is StepStatus.FAILED
    # A failed step is still active work, and still blocks its dependents.
    assert "s-load" in state.active_step_ids
    assert state.ready_step_ids == ()


def test_completion() -> None:
    """Required aggregate case: partial plans, reopen propagation and terminal rules."""
    test_completion_requires_plan_complete()
    test_completion_requires_every_required_step()
    test_completion_succeeds_when_the_guard_passes()
    test_completion_ignores_optional_and_superseded_steps()
    test_completion_terminal_task_rejects_ordinary_mutation()
    test_completion_reopen_blocks_transitive_dependents()
    test_completion_reopen_retains_previous_evidence()
    test_completion_evidence_accumulates_across_attempts()
    test_completion_hint_goes_stale_from_its_neighbourhood()
    test_completion_hint_survives_unrelated_events()
    test_completion_decisions_record_and_retire()
    test_completion_pause_resume_clears_terminal_marker()
    test_completion_failure_does_not_auto_fail_the_task()
