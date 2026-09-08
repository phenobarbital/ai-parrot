"""The pure task-state reducer (FEAT-538, decision D6).

The journal is the source of truth; :class:`TaskState` is a *derived*,
versioned projection of it. This module is that derivation, and it is
deliberately the most boring code in the feature:

    reduce(state: TaskState | None, event: JournalEvent) -> TaskState

**Purity is the contract, not a style preference.** During replay there
are no wall-clock reads, no random identifiers, no validators, no file or
network I/O, and no tool execution. Every timestamp comes from
``event.occurred_at``; every identity comes from the event payload.
Replaying the same sequence twice must produce byte-identical state, on
any host, at any time — otherwise a projection rebuilt after a restart
would silently disagree with the one it replaced.

Consequences that follow from that, and that this module enforces:

- **Validators do not run here.** ``step_completed`` carries the recorded
  ``validator_results``; the reducer consumes them. Re-running a
  validator during replay would make the projection depend on the world's
  current state rather than on the journal.
- **Already-applied sequences are ignored.** A re-delivered event whose
  sequence the projection has already folded in returns the state
  unchanged. A *forward gap* raises: silently skipping an event would
  produce a projection that never existed.
- **A rejected event mutates nothing.** Validation happens before any
  copy is made, and :class:`TaskState` is frozen, so there is no
  partially-applied intermediate.

Handler registry
----------------

:data:`_HANDLERS` maps an :class:`EventType` to its handler. The tool-call,
artifact, degradation and retention families are registered by the
evidence reducer (TASK-2974), which extends this same module. Until they
are, those event types raise :class:`ReducerError` rather than silently
no-op — an unhandled event that quietly changes nothing is exactly the
bug that makes a projection drift from its journal.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .models import Constraint
from .models import Decision as DecisionModel
from .models import (
    DecisionPayload,
    EventType,
    JournalEvent,
    PlanUpdatePayload,
    PlanValidationError,
    ReducerError,
    ResumeHint,
    ResumeHintPayload,
    StepPayload,
    StepStatus,
    TaskLifecyclePayload,
    TaskScope,
    TaskState,
    TaskStatus,
    TaskStep,
)

__all__ = (
    "REDUCER_VERSION",
    "UPSTREAM_REOPENED",
    "PLAN_INCOMPLETE",
    "reduce",
    "replay",
    "validate_plan_graph",
)

#: Version of this reducer's semantics. A projection carrying an older
#: version is lazily replayed under a task lock; an unknown *newer*
#: version is rejected explicitly rather than best-effort interpreted.
REDUCER_VERSION: int = 1

#: Reason stamped on a step blocked because an upstream step reopened.
UPSTREAM_REOPENED: str = "upstream_reopened"

#: Reason a task with an unfinished plan cannot complete.
PLAN_INCOMPLETE: str = "plan_incomplete"

#: Task statuses that accept no ordinary mutation. Create a new task for
#: further work; do not resurrect a terminal one.
_TERMINAL_STATUSES = frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED})

#: The status each task-lifecycle event must move the task to. Recording
#: the mapping explicitly means a payload whose status disagrees with its
#: event type is rejected instead of quietly winning.
_LIFECYCLE_TARGET: Dict[EventType, TaskStatus] = {
    EventType.TASK_STARTED: TaskStatus.ACTIVE,
    EventType.TASK_PAUSED: TaskStatus.PAUSED,
    EventType.TASK_RESUMED: TaskStatus.ACTIVE,
    EventType.TASK_BLOCKED: TaskStatus.BLOCKED,
    EventType.TASK_COMPLETED: TaskStatus.COMPLETED,
    EventType.TASK_FAILED: TaskStatus.FAILED,
    EventType.TASK_CANCELLED: TaskStatus.CANCELLED,
}

#: The status each step event must move the step to.
_STEP_TARGET: Dict[EventType, StepStatus] = {
    EventType.STEP_STARTED: StepStatus.RUNNING,
    EventType.STEP_BLOCKED: StepStatus.BLOCKED,
    EventType.STEP_COMPLETED: StepStatus.COMPLETED,
    EventType.STEP_FAILED: StepStatus.FAILED,
    EventType.STEP_REOPENED: StepStatus.PENDING,
    EventType.STEP_CANCELLED: StepStatus.CANCELLED,
}


# ─────────────────────────────────────────────────────────────
# Plan graph validation
# ─────────────────────────────────────────────────────────────


def validate_plan_graph(steps: Tuple[TaskStep, ...]) -> None:
    """Validate a plan's dependency graph.

    Args:
        steps: The whole plan after a proposed change.

    Raises:
        PlanValidationError: If a step id repeats, a dependency names a
            step that does not exist, or the dependency graph contains a
            cycle. All three are rejected against the *resulting* plan,
            so a batch that would create a cycle only in combination is
            still caught.
    """
    ids = [step.step_id for step in steps]
    if len(set(ids)) != len(ids):
        duplicates = sorted({sid for sid in ids if ids.count(sid) > 1})
        raise PlanValidationError(f"duplicate step ids in plan: {duplicates}")

    by_id = {step.step_id: step for step in steps}
    for step in steps:
        missing = [dep for dep in step.depends_on if dep not in by_id]
        if missing:
            raise PlanValidationError(f"step {step.step_id} depends on unknown steps: {sorted(missing)}")

    # Iterative DFS with three-colour marking — recursion would cap the
    # plan depth at Python's recursion limit rather than at MAX_STEPS.
    WHITE, GREY, BLACK = 0, 1, 2
    colour: Dict[str, int] = {sid: WHITE for sid in by_id}

    for root in ids:
        if colour[root] != WHITE:
            continue
        stack: List[Tuple[str, bool]] = [(root, False)]
        while stack:
            node, finished = stack.pop()
            if finished:
                colour[node] = BLACK
                continue
            if colour[node] == GREY:
                raise PlanValidationError(f"plan dependency cycle detected at step {node}")
            if colour[node] == BLACK:
                continue
            colour[node] = GREY
            stack.append((node, True))
            for dep in by_id[node].depends_on:
                if colour[dep] == GREY:
                    raise PlanValidationError(f"plan dependency cycle detected at step {dep}")
                if colour[dep] == WHITE:
                    stack.append((dep, False))


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────


def _require_step(state: TaskState, step_id: str) -> TaskStep:
    """Return a step by id.

    Args:
        state: The current projection.
        step_id: The step to find.

    Returns:
        The step.

    Raises:
        ReducerError: If no such step exists. An event naming a step the
            plan never had is malformed, not a no-op.
    """
    step = state.steps_by_id.get(step_id)
    if step is None:
        raise ReducerError(f"event references unknown step {step_id!r}")
    return step


def _replace_step(state: TaskState, updated: TaskStep) -> Tuple[TaskStep, ...]:
    """Return the plan with one step replaced, preserving order.

    Args:
        state: The current projection.
        updated: The replacement step.

    Returns:
        The new plan tuple.
    """
    return tuple(updated if s.step_id == updated.step_id else s for s in state.steps)


def _dependents_of(steps: Tuple[TaskStep, ...], step_id: str) -> List[str]:
    """Return the ids of steps that depend on ``step_id``, transitively.

    Args:
        steps: The whole plan.
        step_id: The upstream step.

    Returns:
        Every transitive dependent's id, in stable plan order.
    """
    dependents: set = set()
    frontier = {step_id}
    while frontier:
        nxt: set = set()
        for step in steps:
            if step.step_id in dependents or step.step_id == step_id:
                continue
            if frontier & set(step.depends_on):
                dependents.add(step.step_id)
                nxt.add(step.step_id)
        frontier = nxt
    return [s.step_id for s in steps if s.step_id in dependents]


def _mark_hint_stale(
    hint: Optional[ResumeHint],
    *,
    touched_step_ids: Tuple[str, ...],
    steps: Tuple[TaskStep, ...],
) -> Optional[ResumeHint]:
    """Mark a resume hint stale when a later event undermines it.

    A hint goes stale when an event touches the step it names, or any
    step that step depends on, or any step that depends on it. Staleness
    is *derived* — the agent never authors it — so recall can label a
    hint honestly instead of replaying advice the world has moved past.

    Args:
        hint: The current hint, if any.
        touched_step_ids: Steps the event affected.
        steps: The plan, for resolving the dependency neighbourhood.

    Returns:
        The hint, marked stale when appropriate, or ``None``.
    """
    if hint is None or hint.stale or not touched_step_ids:
        return hint
    if hint.step_id is None:
        return hint

    by_id = {s.step_id: s for s in steps}
    neighbourhood = {hint.step_id}
    anchor = by_id.get(hint.step_id)
    if anchor is not None:
        neighbourhood.update(anchor.depends_on)
        neighbourhood.update(_dependents_of(steps, hint.step_id))

    if neighbourhood & set(touched_step_ids):
        return hint.model_copy(update={"stale": True})
    return hint


# ─────────────────────────────────────────────────────────────
# Handlers
# ─────────────────────────────────────────────────────────────


def _reduce_task_lifecycle(state: TaskState, event: JournalEvent, revision: int) -> TaskState:
    """Apply a task-level transition.

    Args:
        state: The current projection.
        event: The lifecycle event.
        revision: The revision this event produces.

    Returns:
        The new projection.

    Raises:
        ReducerError: If the payload's status disagrees with the event
            type, or a completion is attempted while the completion guard
            would fail.
    """
    payload = event.payload
    assert isinstance(payload, TaskLifecyclePayload)  # guaranteed by JournalEvent validation

    target = _LIFECYCLE_TARGET[event.event_type]
    if payload.status is not target:
        raise ReducerError(f"{event.event_type.value} must carry status {target.value!r}, got {payload.status.value!r}")

    if event.event_type is EventType.TASK_STARTED:
        raise ReducerError("task_started may only be the first event of a task")

    if event.event_type is EventType.TASK_COMPLETED and not state.can_complete:
        # An exhausted partial plan stays active. This is the guard that
        # stops "every step I happened to run finished" from being
        # mistaken for "the work is done".
        detail = PLAN_INCOMPLETE if not state.plan_complete else "required steps are not all completed"
        raise ReducerError(f"task {state.task_id} cannot complete: {detail}")

    update: Dict[str, object] = {"status": target}
    if target in _TERMINAL_STATUSES:
        update["terminal_at"] = event.occurred_at
    elif state.terminal_at is not None:
        update["terminal_at"] = None
    return state.model_copy(update=update)


def _reduce_plan_updated(state: TaskState, event: JournalEvent, revision: int) -> TaskState:
    """Apply a plan revision: additions, patches, supersessions, constraints.

    Args:
        state: The current projection.
        event: The ``plan_updated`` event.
        revision: The revision this event produces.

    Returns:
        The new projection.

    Raises:
        ReducerError: If a patched or superseded step does not exist, or
            a patch would edit a completed step in place.
        PlanValidationError: If the resulting plan has duplicate ids,
            missing dependencies or a cycle.
    """
    payload = event.payload
    assert isinstance(payload, PlanUpdatePayload)

    steps: List[TaskStep] = list(state.steps)
    by_index = {step.step_id: idx for idx, step in enumerate(steps)}

    # 1. Additions.
    for spec in payload.added_steps:
        if spec.step_id in by_index:
            raise PlanValidationError(f"step {spec.step_id} already exists; identities are immutable")
        steps.append(
            TaskStep(
                step_id=spec.step_id,
                title=spec.title,
                description=spec.description,
                required=spec.required,
                depends_on=spec.depends_on,
                completion_policy=spec.completion_policy,
                created_revision=revision,
                updated_revision=revision,
            )
        )
        by_index[spec.step_id] = len(steps) - 1

    # 2. Patches. A completed step's criteria and inputs cannot be edited
    #    in place — reopen it explicitly instead. Silently rewriting what
    #    a completed step was supposed to prove would retroactively
    #    change the meaning of evidence already accepted.
    for patch in payload.updated_steps:
        idx = by_index.get(patch.step_id)
        if idx is None:
            raise ReducerError(f"plan_updated patches unknown step {patch.step_id!r}")
        current = steps[idx]
        if current.status is StepStatus.COMPLETED:
            changes_criteria = patch.completion_policy is not None or patch.depends_on is not None
            if changes_criteria:
                raise PlanValidationError(
                    f"step {patch.step_id} is completed; reopen it before changing its "
                    "criteria or inputs — completed work cannot be redefined in place"
                )
        update = {
            field: value
            for field, value in (
                ("title", patch.title),
                ("description", patch.description),
                ("required", patch.required),
                ("depends_on", patch.depends_on),
                ("completion_policy", patch.completion_policy),
            )
            if value is not None
        }
        update["updated_revision"] = revision
        steps[idx] = current.model_copy(update=update)

    # 3. Supersessions. A retired step keeps its evidence and history.
    for step_id in payload.superseded_step_ids:
        idx = by_index.get(step_id)
        if idx is None:
            raise ReducerError(f"plan_updated supersedes unknown step {step_id!r}")
        steps[idx] = steps[idx].model_copy(update={"status": StepStatus.SUPERSEDED, "updated_revision": revision})

    plan = tuple(steps)
    validate_plan_graph(plan)

    # 4. Constraints.
    constraints: List[Constraint] = list(state.constraints)
    existing_constraints = {c.constraint_id: idx for idx, c in enumerate(constraints)}
    for spec in payload.added_constraints:
        if spec.constraint_id in existing_constraints:
            raise PlanValidationError(f"constraint {spec.constraint_id} already exists")
        constraints.append(Constraint(constraint_id=spec.constraint_id, text=spec.text, revision=revision))
        existing_constraints[spec.constraint_id] = len(constraints) - 1
    for spec in payload.updated_constraints:
        idx = existing_constraints.get(spec.constraint_id)
        if idx is None:
            raise ReducerError(f"plan_updated rewords unknown constraint {spec.constraint_id!r}")
        constraints[idx] = constraints[idx].model_copy(update={"text": spec.text, "revision": revision})
    for constraint_id in payload.deactivated_constraint_ids:
        idx = existing_constraints.get(constraint_id)
        if idx is None:
            raise ReducerError(f"plan_updated deactivates unknown constraint {constraint_id!r}")
        constraints[idx] = constraints[idx].model_copy(update={"active": False, "revision": revision})

    update = {
        "steps": plan,
        "constraints": tuple(constraints),
        "plan_revision": state.plan_revision + 1,
    }
    if payload.plan_complete is not None:
        update["plan_complete"] = payload.plan_complete

    hint = _mark_hint_stale(state.resume_hint, touched_step_ids=payload.touched_step_ids, steps=plan)
    if hint is not state.resume_hint:
        update["resume_hint"] = hint
    return state.model_copy(update=update)


def _reduce_step(state: TaskState, event: JournalEvent, revision: int) -> TaskState:
    """Apply a step-level transition.

    ``step_reopened`` additionally blocks every transitive dependent with
    :data:`UPSTREAM_REOPENED`. Readiness is restored only when the
    upstream step completes again *and* each dependent is explicitly
    revalidated — never merely because some tool succeeded.

    Args:
        state: The current projection.
        event: The step event.
        revision: The revision this event produces.

    Returns:
        The new projection.

    Raises:
        ReducerError: If the step is unknown, the payload's status
            disagrees with the event type, or the step is superseded.
    """
    payload = event.payload
    assert isinstance(payload, StepPayload)

    target = _STEP_TARGET[event.event_type]
    if payload.status is not target:
        raise ReducerError(f"{event.event_type.value} must carry status {target.value!r}, got {payload.status.value!r}")

    step = _require_step(state, payload.step_id)
    if step.status is StepStatus.SUPERSEDED:
        raise ReducerError(f"step {step.step_id} is superseded and accepts no further transitions")

    update: Dict[str, object] = {"status": target, "updated_revision": revision}

    if event.event_type is EventType.STEP_COMPLETED:
        # Evidence accumulates: completing a step never discards what an
        # earlier attempt proved.
        merged = list(step.evidence_refs)
        for ref in payload.evidence_refs:
            if ref not in merged:
                merged.append(ref)
        update["evidence_refs"] = tuple(merged)
        update["completion_source"] = payload.completion_source
        update["completion_note"] = payload.note
        update["blocked_reason"] = None
    elif event.event_type is EventType.STEP_BLOCKED:
        update["blocked_reason"] = payload.reason
    elif event.event_type is EventType.STEP_REOPENED:
        # Previous evidence is retained deliberately: reopening asks for
        # revalidation, it does not erase history.
        update["completion_source"] = None
        update["completion_note"] = None
        update["blocked_reason"] = None
    elif event.event_type is EventType.STEP_STARTED:
        update["blocked_reason"] = None

    steps = _replace_step(state, step.model_copy(update=update))
    touched: List[str] = [step.step_id]

    if event.event_type is EventType.STEP_REOPENED:
        downstream = set(_dependents_of(steps, step.step_id))
        blocked: List[TaskStep] = []
        for candidate in steps:
            if candidate.step_id in downstream and candidate.status in {
                StepStatus.COMPLETED,
                StepStatus.PENDING,
                StepStatus.RUNNING,
            }:
                blocked.append(
                    candidate.model_copy(
                        update={
                            "status": StepStatus.BLOCKED,
                            "blocked_reason": UPSTREAM_REOPENED,
                            "updated_revision": revision,
                            "completion_source": None,
                        }
                    )
                )
                touched.append(candidate.step_id)
        by_id = {s.step_id: s for s in blocked}
        steps = tuple(by_id.get(s.step_id, s) for s in steps)

    new_state = state.model_copy(update={"steps": steps})
    hint = _mark_hint_stale(state.resume_hint, touched_step_ids=tuple(touched), steps=steps)
    if hint is not state.resume_hint:
        new_state = new_state.model_copy(update={"resume_hint": hint})
    return new_state


def _reduce_decision(state: TaskState, event: JournalEvent, revision: int) -> TaskState:
    """Record a decision, or retire an existing one.

    Args:
        state: The current projection.
        event: The ``decision_recorded`` event.
        revision: The revision this event produces.

    Returns:
        The new projection.

    Raises:
        ReducerError: If the event retires a decision that does not
            exist.
    """
    payload = event.payload
    assert isinstance(payload, DecisionPayload)

    decisions = list(state.decisions)
    existing = {d.decision_id: idx for idx, d in enumerate(decisions)}
    idx = existing.get(payload.decision_id)

    if idx is not None:
        decisions[idx] = decisions[idx].model_copy(
            update={
                "text": payload.text,
                "reason": payload.reason,
                "affected_step_ids": payload.affected_step_ids,
                "active": payload.active,
                "revision": revision,
            }
        )
    elif not payload.active:
        raise ReducerError(f"decision_recorded retires unknown decision {payload.decision_id!r}")
    else:
        decisions.append(
            DecisionModel(
                decision_id=payload.decision_id,
                text=payload.text,
                reason=payload.reason,
                actor=event.actor,
                affected_step_ids=payload.affected_step_ids,
                revision=revision,
                active=True,
            )
        )

    return state.model_copy(update={"decisions": tuple(decisions)})


def _reduce_resume_hint(state: TaskState, event: JournalEvent, revision: int) -> TaskState:
    """Replace the resume hint.

    A newly recorded hint is never stale: staleness is derived from
    events that happen *after* it.

    Args:
        state: The current projection.
        event: The ``resume_hint_updated`` event.
        revision: The revision this event produces.

    Returns:
        The new projection.

    Raises:
        ReducerError: If the hint names a step the plan does not have.
    """
    payload = event.payload
    assert isinstance(payload, ResumeHintPayload)

    if payload.step_id is not None:
        _require_step(state, payload.step_id)

    return state.model_copy(
        update={
            "resume_hint": ResumeHint(
                text=payload.text,
                step_id=payload.step_id,
                actor=event.actor,
                revision=revision,
                stale=False,
            )
        }
    )


#: Event type to handler. TASK-2974 registers the tool-call, artifact,
#: degradation and retention families into this same mapping.
_HANDLERS: Dict[EventType, Callable[[TaskState, JournalEvent, int], TaskState]] = {
    EventType.TASK_PAUSED: _reduce_task_lifecycle,
    EventType.TASK_RESUMED: _reduce_task_lifecycle,
    EventType.TASK_BLOCKED: _reduce_task_lifecycle,
    EventType.TASK_COMPLETED: _reduce_task_lifecycle,
    EventType.TASK_FAILED: _reduce_task_lifecycle,
    EventType.TASK_CANCELLED: _reduce_task_lifecycle,
    EventType.TASK_STARTED: _reduce_task_lifecycle,
    EventType.PLAN_UPDATED: _reduce_plan_updated,
    EventType.DECISION_RECORDED: _reduce_decision,
    EventType.RESUME_HINT_UPDATED: _reduce_resume_hint,
    EventType.STEP_STARTED: _reduce_step,
    EventType.STEP_BLOCKED: _reduce_step,
    EventType.STEP_COMPLETED: _reduce_step,
    EventType.STEP_FAILED: _reduce_step,
    EventType.STEP_REOPENED: _reduce_step,
    EventType.STEP_CANCELLED: _reduce_step,
}

#: Event types that remain legal after a task reaches a terminal status.
#: Recovery, honest degradation and retention intent must still be
#: recordable on a finished task; ordinary work must not.
_TERMINAL_SAFE_EVENTS = frozenset(
    {
        EventType.TOOL_OUTCOME_UNKNOWN,
        EventType.TRACKING_DEGRADED,
        EventType.RETENTION_SCHEDULED,
        EventType.ARTIFACT_INVALIDATED,
    }
)


# ─────────────────────────────────────────────────────────────
# Entry points
# ─────────────────────────────────────────────────────────────


def reduce(
    state: Optional[TaskState],
    event: JournalEvent,
    *,
    scope: Optional[TaskScope] = None,
) -> TaskState:
    """Fold one journal event into a task's projection.

    Pure and deterministic: given the same ``(state, event, scope)`` it
    always returns the same result, with no clock, randomness, validator
    or I/O involved.

    Args:
        state: The projection so far, or ``None`` to begin a task. Only
            a ``task_started`` event may begin one.
        event: The event to apply. Its ``seq`` must be exactly
            ``state.last_event_seq + 1``, or a value already folded in.
        scope: The trusted scope to stamp on a *new* projection.
            Required when ``state`` is ``None`` and ignored otherwise.
            Scope lives on the task row, not on every event: the store
            owns it and has already checked it before the reducer runs.

    Returns:
        The new projection. When ``event`` was already applied, the
        *same* state object is returned unchanged.

    Raises:
        ReducerError: If the event is malformed for the current state:
            a missing or duplicate task start, a task id mismatch, a
            forward sequence gap, an unsupported reducer version, an
            unhandled event family, an ordinary mutation of a terminal
            task, or a payload that contradicts its event type.
        PlanValidationError: If a plan change would produce an invalid
            graph.
    """
    if state is None:
        return _begin(event, scope)

    if event.task_id != state.task_id:
        raise ReducerError(f"event belongs to task {event.task_id!r}, not {state.task_id!r}")

    if state.reducer_version != REDUCER_VERSION:
        raise ReducerError(
            f"projection was produced by reducer version {state.reducer_version}, "
            f"this build implements {REDUCER_VERSION}"
        )

    if event.seq and event.seq <= state.last_event_seq:
        # Already folded in. Returning the identical object (not a copy)
        # makes "this changed nothing" observable to callers.
        return state

    expected_seq = state.last_event_seq + 1
    if event.seq and event.seq != expected_seq:
        raise ReducerError(
            f"sequence gap on task {state.task_id}: expected {expected_seq}, got {event.seq}. "
            "A projection must never skip an event."
        )

    handler = _HANDLERS.get(event.event_type)
    if handler is None:
        raise ReducerError(
            f"no reducer handler for {event.event_type.value!r}; "
            "an unhandled event must not silently leave the projection unchanged"
        )

    if state.status in _TERMINAL_STATUSES and event.event_type not in _TERMINAL_SAFE_EVENTS:
        raise ReducerError(
            f"task {state.task_id} is {state.status.value} and accepts no ordinary mutation; "
            "create a new task for further work"
        )

    revision = state.revision + 1
    new_state = handler(state, event, revision)

    return new_state.model_copy(
        update={
            "revision": revision,
            "last_event_seq": event.seq or expected_seq,
            "updated_at": event.occurred_at,
        }
    )


def _begin(event: JournalEvent, scope: Optional[TaskScope]) -> TaskState:
    """Create a task's initial projection from its ``task_started`` event.

    Args:
        event: The first event.
        scope: The trusted scope to stamp on the projection.

    Returns:
        The initial projection.

    Raises:
        ReducerError: If the event is not a ``task_started``, is not the
            first in the journal, carries no goal, or arrives without a
            scope to attribute it to.
    """
    if scope is None:
        raise ReducerError("beginning a task requires the trusted scope it belongs to")
    if event.event_type is not EventType.TASK_STARTED:
        raise ReducerError(f"a task's first event must be task_started, got {event.event_type.value!r}")
    if event.seq not in (0, 1):
        raise ReducerError(f"task_started must be sequence 1, got {event.seq}")

    payload = event.payload
    if not isinstance(payload, TaskLifecyclePayload):
        raise ReducerError("task_started requires a task_lifecycle payload")
    if payload.status is not TaskStatus.ACTIVE:
        raise ReducerError(f"task_started must carry status 'active', got {payload.status.value!r}")
    if not payload.goal:
        raise ReducerError("task_started must carry the task's goal")

    return TaskState(
        task_id=event.task_id,
        scope=scope,
        goal=payload.goal,
        status=TaskStatus.ACTIVE,
        revision=1,
        last_event_seq=event.seq or 1,
        created_at=event.occurred_at,
        updated_at=event.occurred_at,
        reducer_version=REDUCER_VERSION,
    )


def replay(events: Sequence[JournalEvent], *, scope: TaskScope) -> Optional[TaskState]:
    """Rebuild a projection by folding a whole journal.

    This is the operation that must be reproducible: replaying the same
    events on any host, at any time, yields byte-identical state. It is
    what a lazy projection migration runs under a task lock when the
    stored reducer version is older than this build's.

    Args:
        events: The journal, in ascending sequence order.
        scope: The trusted scope the task belongs to.

    Returns:
        The final projection, or ``None`` for an empty journal.

    Raises:
        ReducerError: If the journal is malformed (see :func:`reduce`).
        PlanValidationError: If a recorded plan change is invalid.
    """
    state: Optional[TaskState] = None
    for event in events:
        state = reduce(state, event, scope=scope)
    return state
