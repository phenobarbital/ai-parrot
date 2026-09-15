"""Reducer tests for call outcomes and evidence invalidation (TASK-2974).

Three required cases from the task's Test Specification:

- ``test_dedup_count`` — duplicate delivery and aggregate plan results
  cannot double-count physical attempts.
- ``test_failure_provenance`` — unattributed failures stay task-level,
  and an unrelated success cannot clear an unresolved outcome.
- ``test_evidence_reopen`` — invalidating a bound *version* blocks
  evidence-dependent completion, while overwriting an *alias* alone does
  not.

Each is a group of focused functions plus an aggregate carrying the
required name, so a failure names the invariant that broke.

The governing rule behind all of it (AC3): a tool result is never
evidence. Nothing in this module can move a step to ``completed``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

import pytest
from parrot.tools.working_memory.task_memory.models import (
    ArtifactKind,
    ArtifactPayload,
    Attribution,
    CallOutcome,
    CompletionSource,
    EventType,
    EvidenceRef,
    JournalEvent,
    PlanStepSpec,
    PlanUpdatePayload,
    ReducerError,
    ResumeHintPayload,
    StepPayload,
    StepStatus,
    TaskLifecyclePayload,
    TaskScope,
    TaskState,
    TaskStatus,
    ToolCallPayload,
)
from parrot.tools.working_memory.task_memory.reducer import (
    EVIDENCE_INVALIDATED,
    MAX_ATTEMPTS,
    MAX_ATTEMPTS_EXHAUSTED,
    UPSTREAM_REOPENED,
    reduce,
    replay,
)

SCOPE = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")

#: A fixed instant. The reducer must never read a clock.
T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

#: Two distinct versions of the SAME artifact identity — an overwrite.
REF_V1 = EvidenceRef(artifact_id="sales", version=1)
REF_V2 = EvidenceRef(artifact_id="sales", version=2)
#: A different artifact entirely.
OTHER_REF = EvidenceRef(artifact_id="prices", version=1)


class _Journal:
    """Builds a deterministic, correctly sequenced journal."""

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

    def call(
        self,
        event_type: EventType,
        *,
        call_id: str = "c1",
        step_id: Optional[str] = None,
        attribution: Attribution = Attribution.NONE,
        outcome: Optional[CallOutcome] = None,
        counted: bool = True,
        executed: bool = True,
        parent_call_id: Optional[str] = None,
        tool_name: str = "wm_store",
        **payload_kwargs: object,
    ) -> "_Journal":
        """Append a tool-call lifecycle event.

        Args:
            event_type: Which tool event.
            call_id: Identity of the physical attempt.
            step_id: Step correlation, when attributed.
            attribution: How the correlation was established.
            outcome: Typed outcome; inferred from ``event_type`` when
                ``None`` and the event is terminal.
            counted: Whether this terminal event does the counting.
            executed: Whether a tool body actually ran.
            parent_call_id: Parent aggregate, when nested.
            tool_name: The dispatched tool.
            **payload_kwargs: Extra :class:`ToolCallPayload` fields.

        Returns:
            This journal, for chaining.
        """
        if outcome is None and event_type is not EventType.TOOL_STARTED:
            outcome = {
                EventType.TOOL_SUCCEEDED: CallOutcome.SUCCESS,
                EventType.TOOL_FAILED: CallOutcome.ERROR,
                EventType.TOOL_CANCELLED: CallOutcome.CANCELLED,
                EventType.TOOL_OUTCOME_UNKNOWN: CallOutcome.UNKNOWN,
            }[event_type]
        payload = ToolCallPayload(
            call_id=call_id,
            tool_name=tool_name,
            outcome=outcome,
            counted=counted,
            executed=executed,
            **payload_kwargs,  # type: ignore[arg-type]
        )
        self.add(
            event_type,
            payload,
            step_id=step_id,
            attribution=attribution,
            parent_call_id=parent_call_id,
        )
        return self

    def artifact(self, event_type: EventType, ref: EvidenceRef, **kwargs: object) -> "_Journal":
        """Append an artifact registration or invalidation.

        Args:
            event_type: Which artifact event.
            ref: The exact artifact version.
            **kwargs: Extra :class:`ArtifactPayload` fields.

        Returns:
            This journal, for chaining.
        """
        self.add(event_type, ArtifactPayload(ref=ref, **kwargs))  # type: ignore[arg-type]
        return self

    def complete_step(self, step_id: str, *, evidence: tuple = ()) -> "_Journal":
        """Complete a step, binding exact evidence versions.

        Args:
            step_id: The step to complete.
            evidence: Exact artifact versions to bind.

        Returns:
            This journal, for chaining.
        """
        self.add(
            EventType.STEP_COMPLETED,
            StepPayload(
                step_id=step_id,
                status=StepStatus.COMPLETED,
                evidence_refs=evidence,
                note="done",
                completion_source=CompletionSource.VALIDATED,
            ),
        )
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


def _plan() -> _Journal:
    """Return a started task with a load → clean → report plan."""
    return (
        _Journal()
        .start()
        .plan(
            added_steps=(
                PlanStepSpec(step_id="s-load", title="Load raw data"),
                PlanStepSpec(step_id="s-clean", title="Clean data", depends_on=("s-load",)),
                PlanStepSpec(step_id="s-report", title="Write report", depends_on=("s-clean",)),
            )
        )
    )


def _attributed(**kwargs: object) -> dict:
    """Return kwargs for a call unambiguously attributed to ``s-load``.

    Args:
        **kwargs: Overrides.

    Returns:
        Keyword arguments for :meth:`_Journal.call`.
    """
    base = {"step_id": "s-load", "attribution": Attribution.DECLARED}
    base.update(kwargs)
    return base


# ─────────────────────────────────────────────────────────────
# Attempt counting and de-duplication
# ─────────────────────────────────────────────────────────────


def test_dedup_count_counts_one_attempt_per_terminal_event() -> None:
    """One counted, executed, attributed terminal event is one attempt."""
    state = _plan().call(EventType.TOOL_SUCCEEDED, **_attributed()).build()
    assert state.steps_by_id["s-load"].attempt_count == 1


def test_dedup_count_started_events_never_count() -> None:
    """A started call is not a completed attempt and changes nothing."""
    journal = _plan().call(EventType.TOOL_STARTED, **_attributed())
    state = journal.build()
    assert state.steps_by_id["s-load"].attempt_count == 0
    assert state.steps_by_id["s-load"].status is StepStatus.PENDING


def test_dedup_count_duplicate_delivery_cannot_double_count() -> None:
    """Re-applying an already-folded event changes nothing at all."""
    journal = _plan().call(EventType.TOOL_FAILED, **_attributed())
    state = journal.build()
    assert state.steps_by_id["s-load"].attempt_count == 1

    replayed = reduce(state, journal.events[-1])
    assert replayed is state, "a re-delivered event must be an exact no-op"
    assert replayed.steps_by_id["s-load"].attempt_count == 1

    # And a full replay of the same journal is idempotent too.
    assert journal.build() == state


def test_dedup_count_aggregate_parent_does_not_double_count_children() -> None:
    """A plan node's aggregate result is not a second execution of its child.

    The child attempt carries ``counted=True``; the parent aggregate that
    wraps it carries ``counted=False``. Both are recorded, but only one
    is a physical attempt.
    """
    journal = _plan()
    journal.call(
        EventType.TOOL_SUCCEEDED,
        **_attributed(call_id="child-1", parent_call_id="parent-1", counted=True),
    )
    journal.call(
        EventType.TOOL_SUCCEEDED,
        **_attributed(call_id="parent-1", counted=False),
    )
    state = journal.build()
    assert state.steps_by_id["s-load"].attempt_count == 1, "the aggregate parent must not be counted"


def test_dedup_count_unexecuted_dispatch_is_not_a_physical_attempt() -> None:
    """A denial or unknown tool never ran a body, so it is not an attempt."""
    for outcome in (CallOutcome.DENIED, CallOutcome.NOT_EXECUTED):
        state = _plan().call(EventType.TOOL_FAILED, **_attributed(outcome=outcome, executed=False)).build()
        assert state.steps_by_id["s-load"].attempt_count == 0, f"{outcome.value} must not count"
        assert state.steps_by_id["s-load"].status is StepStatus.PENDING


def test_dedup_count_repeated_failures_block_at_the_ceiling() -> None:
    """The third attributed executed failure blocks the step for review."""
    journal = _plan()
    for n in range(MAX_ATTEMPTS):
        journal.call(EventType.TOOL_FAILED, **_attributed(call_id=f"c{n}"))
        state = journal.build()
        step = state.steps_by_id["s-load"]
        assert step.attempt_count == n + 1
        if n + 1 < MAX_ATTEMPTS:
            assert step.status is StepStatus.PENDING, "a failure below the ceiling does not block"
            assert step.blocked_reason is None

    step = journal.build().steps_by_id["s-load"]
    assert step.status is StepStatus.BLOCKED
    assert step.blocked_reason == MAX_ATTEMPTS_EXHAUSTED
    # Blocked, never failed: "failure does not auto-fail the step or task".
    assert step.status is not StepStatus.FAILED
    assert journal.build().status is TaskStatus.ACTIVE


def test_dedup_count_ceiling_only_applies_to_failures() -> None:
    """Successes count as attempts but never block, however many there are."""
    journal = _plan()
    for n in range(MAX_ATTEMPTS + 2):
        journal.call(EventType.TOOL_SUCCEEDED, **_attributed(call_id=f"c{n}"))
    step = journal.build().steps_by_id["s-load"]
    assert step.attempt_count == MAX_ATTEMPTS + 2
    assert step.status is StepStatus.PENDING, "success never blocks and never completes"
    assert step.blocked_reason is None


def test_dedup_count_unresolved_outcomes_never_block() -> None:
    """Cancelled and unknown outcomes count but never establish failure."""
    for event_type in (EventType.TOOL_CANCELLED, EventType.TOOL_OUTCOME_UNKNOWN):
        journal = _plan()
        for n in range(MAX_ATTEMPTS + 1):
            journal.call(event_type, **_attributed(call_id=f"c{n}"))
        step = journal.build().steps_by_id["s-load"]
        assert step.attempt_count == MAX_ATTEMPTS + 1
        assert step.status is StepStatus.PENDING, f"{event_type.value} must not block"
        assert step.blocked_reason is None


def test_dedup_count_tool_events_do_not_advance_revision() -> None:
    """An immaterial event advances sequence and activity, not revision.

    If every observed tool call bumped the revision, an agent's
    ``expected_revision`` would be stale after any tool call and every
    step update would fail with a conflict through no fault of its own.
    """
    journal = _plan()
    before = journal.build()

    journal.call(EventType.TOOL_STARTED, **_attributed())
    journal.call(EventType.TOOL_SUCCEEDED, **_attributed(step_id=None, attribution=Attribution.NONE))
    journal.artifact(EventType.ARTIFACT_REGISTERED, REF_V1, alias="sales", artifact_kind=ArtifactKind.DATAFRAME)
    after = journal.build()

    assert after.revision == before.revision, "immaterial events must not advance the revision"
    assert after.last_event_seq > before.last_event_seq, "but the journal did advance"
    assert after.updated_at > before.updated_at, "and the task was active"


def test_dedup_count_material_tool_events_do_advance_revision() -> None:
    """A counted attributed attempt changes the projection, so it counts."""
    journal = _plan()
    before = journal.build()
    journal.call(EventType.TOOL_FAILED, **_attributed())
    after = journal.build()
    assert after.revision == before.revision + 1


def test_dedup_count_rejects_contradictory_outcomes() -> None:
    """A payload whose outcome disagrees with its event type never wins."""
    journal = _plan()
    journal.call(EventType.TOOL_FAILED, **_attributed(outcome=CallOutcome.SUCCESS))
    with pytest.raises(ReducerError, match="must arrive on"):
        journal.build()

    started = _plan()
    started.call(EventType.TOOL_STARTED, **_attributed(outcome=CallOutcome.SUCCESS))
    with pytest.raises(ReducerError, match="must not carry a terminal outcome"):
        started.build()

    missing = _plan()
    missing.add(
        EventType.TOOL_SUCCEEDED,
        ToolCallPayload(call_id="c1", tool_name="wm_store", outcome=None),
        step_id="s-load",
        attribution=Attribution.DECLARED,
    )
    with pytest.raises(ReducerError, match="must carry a typed outcome"):
        missing.build()


def test_dedup_count_rejects_unknown_steps() -> None:
    """A call attributed to a step the plan never had is malformed."""
    journal = _plan().call(EventType.TOOL_SUCCEEDED, step_id="ghost", attribution=Attribution.DECLARED)
    with pytest.raises(ReducerError, match="unknown step"):
        journal.build()


def test_dedup_count_ignores_calls_against_superseded_steps() -> None:
    """A late result for a retired step counts nothing and raises nothing.

    Raising would make a plausible real-world ordering permanently
    unreplayable, which would wedge the journal.
    """
    journal = _plan().plan(superseded_step_ids=("s-load",)).call(EventType.TOOL_FAILED, **_attributed())
    step = journal.build().steps_by_id["s-load"]
    assert step.status is StepStatus.SUPERSEDED
    assert step.attempt_count == 0


def test_dedup_count() -> None:
    """Required aggregate case: attempts are counted exactly once."""
    test_dedup_count_counts_one_attempt_per_terminal_event()
    test_dedup_count_started_events_never_count()
    test_dedup_count_duplicate_delivery_cannot_double_count()
    test_dedup_count_aggregate_parent_does_not_double_count_children()
    test_dedup_count_unexecuted_dispatch_is_not_a_physical_attempt()
    test_dedup_count_repeated_failures_block_at_the_ceiling()
    test_dedup_count_ceiling_only_applies_to_failures()
    test_dedup_count_unresolved_outcomes_never_block()
    test_dedup_count_tool_events_do_not_advance_revision()
    test_dedup_count_material_tool_events_do_advance_revision()
    test_dedup_count_rejects_contradictory_outcomes()
    test_dedup_count_rejects_unknown_steps()
    test_dedup_count_ignores_calls_against_superseded_steps()


# ─────────────────────────────────────────────────────────────
# Failure provenance
# ─────────────────────────────────────────────────────────────


def test_failure_provenance_unattributed_failures_stay_task_level() -> None:
    """A failure nobody can attribute is never pinned on a guessed step."""
    journal = _plan()
    journal.call(EventType.TOOL_FAILED, step_id=None, attribution=Attribution.NONE)
    state = journal.build()

    assert all(s.attempt_count == 0 for s in state.steps), "no step may absorb an unattributed failure"
    assert all(s.status is StepStatus.PENDING for s in state.steps)
    assert state.status is TaskStatus.ACTIVE, "and the task is not auto-failed either"


def test_failure_provenance_ambiguous_attribution_stays_task_level() -> None:
    """Two concurrent declarations give ``ambiguous``, which attributes nothing."""
    journal = _plan()
    journal.call(EventType.TOOL_FAILED, step_id="s-load", attribution=Attribution.AMBIGUOUS)
    state = journal.build()
    assert state.steps_by_id["s-load"].attempt_count == 0


def test_failure_provenance_unmapped_plan_call_stays_task_level() -> None:
    """A plan node id is not a step id: an unmapped plan call has no step_id."""
    journal = _plan()
    journal.call(EventType.TOOL_FAILED, step_id=None, attribution=Attribution.PLAN)
    state = journal.build()
    assert all(s.attempt_count == 0 for s in state.steps)

    # An explicitly mapped plan call, by contrast, does attribute.
    mapped = _plan()
    mapped.call(EventType.TOOL_FAILED, step_id="s-load", attribution=Attribution.PLAN)
    assert mapped.build().steps_by_id["s-load"].attempt_count == 1


def test_failure_provenance_success_never_completes_a_step() -> None:
    """The governing rule: a successful tool call is not evidence (AC3)."""
    journal = _plan().call(EventType.TOOL_SUCCEEDED, **_attributed())
    state = journal.build()

    step = state.steps_by_id["s-load"]
    assert step.status is not StepStatus.COMPLETED
    assert step.completion_source is None
    assert step.completion_note is None
    assert step.evidence_refs == (), "a tool result binds no evidence"
    assert state.can_complete is False


def test_failure_provenance_unrelated_success_cannot_clear_a_failure() -> None:
    """A success elsewhere does not resolve an unresolved outcome."""
    journal = _plan()
    for n in range(MAX_ATTEMPTS):
        journal.call(EventType.TOOL_FAILED, **_attributed(call_id=f"f{n}"))
    blocked = journal.build().steps_by_id["s-load"]
    assert blocked.status is StepStatus.BLOCKED
    assert blocked.blocked_reason == MAX_ATTEMPTS_EXHAUSTED

    # A success on a *different* step must not touch the blocked one.
    journal.call(
        EventType.TOOL_SUCCEEDED,
        call_id="ok-1",
        step_id="s-clean",
        attribution=Attribution.DECLARED,
    )
    after = journal.build()
    still_blocked = after.steps_by_id["s-load"]
    assert still_blocked.status is StepStatus.BLOCKED, "an unrelated success cannot unblock"
    assert still_blocked.blocked_reason == MAX_ATTEMPTS_EXHAUSTED
    assert still_blocked.attempt_count == MAX_ATTEMPTS

    # Even a success on the SAME step does not clear the block. Only an
    # explicit step transition may do that.
    journal.call(EventType.TOOL_SUCCEEDED, **_attributed(call_id="ok-2"))
    assert journal.build().steps_by_id["s-load"].status is StepStatus.BLOCKED


def test_failure_provenance_unknown_outcome_stays_unresolved() -> None:
    """An unknown outcome is never resolved by later unrelated activity."""
    journal = _plan()
    journal.call(EventType.TOOL_OUTCOME_UNKNOWN, **_attributed(call_id="u1"))
    unresolved = journal.build().steps_by_id["s-load"]
    assert unresolved.attempt_count == 1
    assert unresolved.status is StepStatus.PENDING

    journal.call(EventType.TOOL_SUCCEEDED, call_id="ok", step_id="s-clean", attribution=Attribution.DECLARED)
    after = journal.build().steps_by_id["s-load"]
    assert after.attempt_count == 1, "an unrelated success changes nothing about the unknown attempt"
    assert after.status is StepStatus.PENDING
    # The unknown outcome remains in the journal, honestly, for recall.
    kinds = [e.event_type for e in journal.events]
    assert EventType.TOOL_OUTCOME_UNKNOWN in kinds


def test_failure_provenance_task_failure_does_not_touch_steps() -> None:
    """A task-level failure stays visible without being assigned to a step."""
    journal = _plan()
    journal.add(EventType.TASK_FAILED, TaskLifecyclePayload(status=TaskStatus.FAILED, reason="giving up"))
    state = journal.build()
    assert state.status is TaskStatus.FAILED
    assert all(s.status is StepStatus.PENDING for s in state.steps)


def test_failure_provenance_degradation_is_recorded_without_inventing_state() -> None:
    """``tracking_degraded`` is an honest gap marker, not a plan change."""
    from parrot.tools.working_memory.task_memory.models import DegradedPayload

    journal = _plan()
    before = journal.build()
    journal.add(
        EventType.TRACKING_DEGRADED,
        DegradedPayload(component="journal", detail="append timed out"),
    )
    after = journal.build()

    assert after.steps == before.steps
    assert after.status == before.status
    assert after.revision == before.revision, "a gap marker invents no state change"
    assert after.last_event_seq == before.last_event_seq + 1


def test_failure_provenance_retention_intent_is_recorded_without_plan_change() -> None:
    """``retention_scheduled`` records intent before destructive work."""
    from parrot.tools.working_memory.task_memory.models import RetentionPayload

    journal = _plan()
    before = journal.build()
    journal.add(
        EventType.RETENTION_SCHEDULED,
        RetentionPayload(policy="terminal", action="archive"),
    )
    after = journal.build()
    assert after.steps == before.steps
    assert after.revision == before.revision


def test_failure_provenance_recovery_events_are_legal_on_a_terminal_task() -> None:
    """A finished task still accepts recovery, degradation and retention."""
    from parrot.tools.working_memory.task_memory.models import DegradedPayload, RetentionPayload

    journal = (
        _Journal()
        .start()
        .plan(added_steps=(PlanStepSpec(step_id="only", title="Only"),), plan_complete=True)
        .complete_step("only")
    )
    journal.add(EventType.TASK_COMPLETED, TaskLifecyclePayload(status=TaskStatus.COMPLETED))
    assert journal.build().status is TaskStatus.COMPLETED

    journal.call(EventType.TOOL_OUTCOME_UNKNOWN, call_id="late", step_id=None)
    journal.add(EventType.TRACKING_DEGRADED, DegradedPayload(component="journal"))
    journal.add(EventType.RETENTION_SCHEDULED, RetentionPayload(policy="terminal", action="delete"))
    assert journal.build().status is TaskStatus.COMPLETED

    # Ordinary work, by contrast, is still refused.
    journal.call(EventType.TOOL_SUCCEEDED, call_id="nope", step_id=None)
    with pytest.raises(ReducerError, match="accepts no ordinary mutation"):
        journal.build()


def test_failure_provenance() -> None:
    """Required aggregate case: failures keep their provenance."""
    test_failure_provenance_unattributed_failures_stay_task_level()
    test_failure_provenance_ambiguous_attribution_stays_task_level()
    test_failure_provenance_unmapped_plan_call_stays_task_level()
    test_failure_provenance_success_never_completes_a_step()
    test_failure_provenance_unrelated_success_cannot_clear_a_failure()
    test_failure_provenance_unknown_outcome_stays_unresolved()
    test_failure_provenance_task_failure_does_not_touch_steps()
    test_failure_provenance_degradation_is_recorded_without_inventing_state()
    test_failure_provenance_retention_intent_is_recorded_without_plan_change()
    test_failure_provenance_recovery_events_are_legal_on_a_terminal_task()


# ─────────────────────────────────────────────────────────────
# Evidence invalidation vs alias overwrite
# ─────────────────────────────────────────────────────────────


def _completed_with_evidence() -> _Journal:
    """Return a journal whose ``s-load`` is completed against ``sales@1``."""
    return _plan().complete_step("s-load", evidence=(REF_V1,))


def test_evidence_reopen_alias_overwrite_alone_does_not_reopen() -> None:
    """Registering a newer version is an overwrite, not a mutation (AC5).

    ``sales@2`` being published says nothing about ``sales@1``, which is
    the exact version the step was completed against. Older evidence
    stays valid and resolvable.
    """
    journal = _completed_with_evidence()
    before = journal.build()
    assert before.steps_by_id["s-load"].status is StepStatus.COMPLETED

    journal.artifact(EventType.ARTIFACT_REGISTERED, REF_V2, alias="sales", artifact_kind=ArtifactKind.DATAFRAME)
    after = journal.build()

    step = after.steps_by_id["s-load"]
    assert step.status is StepStatus.COMPLETED, "an overwrite must not reopen the old version's step"
    assert step.evidence_refs == (REF_V1,)
    assert step.completion_source is CompletionSource.VALIDATED
    assert after.revision == before.revision, "registration is immaterial to the plan"


def test_evidence_reopen_invalidating_the_bound_version_blocks_completion() -> None:
    """Invalidating the exact bound version stops the step counting as complete."""
    journal = _completed_with_evidence()
    journal.artifact(EventType.ARTIFACT_INVALIDATED, REF_V1, alias="sales", reason="source mutated")
    state = journal.build()

    step = state.steps_by_id["s-load"]
    assert step.status is StepStatus.BLOCKED
    assert step.blocked_reason == EVIDENCE_INVALIDATED
    assert step.completion_source is None, "it can no longer claim to be validated"
    assert step.evidence_refs == (REF_V1,), "but what it relied on is retained for revalidation"


def test_evidence_reopen_invalidating_a_different_version_is_inert() -> None:
    """Invalidating ``sales@2`` does not disturb a step bound to ``sales@1``."""
    journal = _completed_with_evidence()
    before = journal.build()
    journal.artifact(EventType.ARTIFACT_INVALIDATED, REF_V2, alias="sales", reason="newer one bad")
    after = journal.build()

    assert after.steps_by_id["s-load"].status is StepStatus.COMPLETED
    assert after.revision == before.revision, "nothing material changed"


def test_evidence_reopen_invalidating_an_unbound_artifact_is_inert() -> None:
    """Invalidating an artifact no step relied on changes nothing."""
    journal = _completed_with_evidence()
    before = journal.build()
    journal.artifact(EventType.ARTIFACT_INVALIDATED, OTHER_REF, reason="unused")
    after = journal.build()
    assert after.steps_by_id["s-load"].status is StepStatus.COMPLETED
    assert after.revision == before.revision


def test_evidence_reopen_blocks_completed_downstream_steps() -> None:
    """A completed downstream step is not left silently valid."""
    journal = _completed_with_evidence().complete_step("s-clean")
    assert journal.build().steps_by_id["s-clean"].status is StepStatus.COMPLETED

    journal.artifact(EventType.ARTIFACT_INVALIDATED, REF_V1, reason="source mutated")
    state = journal.build()

    assert state.steps_by_id["s-load"].blocked_reason == EVIDENCE_INVALIDATED
    downstream = state.steps_by_id["s-clean"]
    assert downstream.status is StepStatus.BLOCKED
    assert downstream.blocked_reason == UPSTREAM_REOPENED
    assert downstream.completion_source is None

    # An untouched, still-pending step is left alone.
    assert state.steps_by_id["s-report"].status is StepStatus.PENDING


def test_evidence_reopen_gates_task_completion() -> None:
    """A task whose evidence was invalidated can no longer complete."""
    journal = (
        _Journal()
        .start()
        .plan(added_steps=(PlanStepSpec(step_id="only", title="Only"),), plan_complete=True)
        .complete_step("only", evidence=(REF_V1,))
    )
    assert journal.build().can_complete is True

    journal.artifact(EventType.ARTIFACT_INVALIDATED, REF_V1, reason="source mutated")
    state = journal.build()
    assert state.can_complete is False

    journal.add(EventType.TASK_COMPLETED, TaskLifecyclePayload(status=TaskStatus.COMPLETED))
    with pytest.raises(ReducerError, match="required steps are not all completed"):
        journal.build()


def test_evidence_reopen_marks_a_dependent_hint_stale() -> None:
    """Advice resting on invalidated evidence is labelled honestly."""
    journal = _completed_with_evidence()
    journal.add(EventType.RESUME_HINT_UPDATED, ResumeHintPayload(text="clean next", step_id="s-clean"))
    assert journal.build().resume_hint.stale is False

    journal.artifact(EventType.ARTIFACT_INVALIDATED, REF_V1, reason="source mutated")
    hint = journal.build().resume_hint
    assert hint is not None and hint.stale is True


def test_evidence_reopen_only_targets_completed_steps() -> None:
    """A step that never completed against the version is not blocked."""
    journal = _plan()
    journal.artifact(EventType.ARTIFACT_INVALIDATED, REF_V1, reason="source mutated")
    state = journal.build()
    assert all(s.status is StepStatus.PENDING for s in state.steps)
    assert all(s.blocked_reason is None for s in state.steps)


def test_evidence_reopen_is_replay_stable() -> None:
    """The whole evidence sequence replays to byte-identical state."""
    journal = _completed_with_evidence().complete_step("s-clean")
    journal.artifact(EventType.ARTIFACT_INVALIDATED, REF_V1, reason="source mutated")
    assert journal.build().model_dump_json() == journal.build().model_dump_json()


def test_evidence_reopen() -> None:
    """Required aggregate case: invalidation blocks, overwrite does not."""
    test_evidence_reopen_alias_overwrite_alone_does_not_reopen()
    test_evidence_reopen_invalidating_the_bound_version_blocks_completion()
    test_evidence_reopen_invalidating_a_different_version_is_inert()
    test_evidence_reopen_invalidating_an_unbound_artifact_is_inert()
    test_evidence_reopen_blocks_completed_downstream_steps()
    test_evidence_reopen_gates_task_completion()
    test_evidence_reopen_marks_a_dependent_hint_stale()
    test_evidence_reopen_only_targets_completed_steps()
    test_evidence_reopen_is_replay_stable()


# ─────────────────────────────────────────────────────────────
# Coverage of the registry itself
# ─────────────────────────────────────────────────────────────


def test_every_event_type_now_has_a_handler() -> None:
    """No event family is left to silently no-op.

    An unhandled event that quietly changes nothing is how a projection
    drifts from its journal, so the registry must be total.
    """
    from parrot.tools.working_memory.task_memory.reducer import _HANDLERS

    missing = set(EventType) - set(_HANDLERS)
    assert missing == set(), f"event types with no reducer handler: {sorted(e.value for e in missing)}"
