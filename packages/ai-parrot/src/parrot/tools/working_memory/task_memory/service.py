"""The task-memory command service (FEAT-538).

Everything above this layer speaks in *commands* — begin a task, revise a
plan, record a decision, set a hint, pause or cancel. Everything below it
speaks in *events*. This module is the translation, and it owns the three
jobs that translation implies:

1. **Minting runtime identities.** Step, constraint and decision ids are
   created here, never accepted from a caller. A model-authored id would
   let one task's command name another task's step.
2. **Resolving request-local labels.** An initial plan cannot reference
   runtime step ids, because none exist yet. Labels are resolved to ids
   **before anything is appended**, so a malformed plan is rejected
   without mutating the task.
3. **Validating whole batches before appending.** Dependencies, cycles,
   duplicate ids and illegal statuses are checked against the *resulting*
   plan. A rejected command leaves the journal and the projection exactly
   as they were.

Scope is runtime-owned. Every method takes a trusted :class:`TaskScope`
as its first argument, and an explicit ``task_id`` is only ever a
*selector within that scope* — never a way to reach across one. A task
belonging to another scope reads as absent, not as forbidden, because an
existence oracle is itself a leak.

Out of scope for this module, deliberately: LLM-facing tool schemas
(TASK-2989) and completion validators (TASK-2980). ``update_step`` here
records a transition; it does not decide whether the evidence justifies
one.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from parrot.interfaces.artifact_store import ArtifactStore
from parrot.interfaces.task_memory import AppendResult, TaskMemoryStore, TaskPage, TaskSnapshot

from .config import TaskMemoryConfig
from .models import (
    Actor,
    AddConstraint,
    AddStep,
    CompletionSource,
    DeactivateConstraint,
    DecisionPayload,
    EventType,
    EvidenceRef,
    InitialStepSpec,
    JournalEvent,
    LimitExceeded,
    Limits,
    PlanChanges,
    PlanConstraintSpec,
    PlanStepPatch,
    PlanStepSpec,
    PlanUpdatePayload,
    PlanValidationError,
    ResumeHintPayload,
    RevisionConflict,
    SetPlanComplete,
    StepPayload,
    StepStatus,
    SupersedeStep,
    TaskLifecyclePayload,
    TaskScope,
    TaskState,
    TaskStatus,
    UpdateConstraint,
    UpdateStep,
    new_id,
    utc_now,
)
from .reducer import validate_plan_graph
from .validators import CompletionValidationError, EvidenceMutated, assert_unchanged, validate_completion

__all__ = (
    "TaskNotFound",
    "TaskMemoryService",
    "CompletionValidationError",
    "EvidenceMutated",
)

#: Which lifecycle event each requested status maps to. A status with no
#: entry is not a legal target for ``update_task``.
_STATUS_EVENT: Dict[TaskStatus, EventType] = {
    TaskStatus.ACTIVE: EventType.TASK_RESUMED,
    TaskStatus.PAUSED: EventType.TASK_PAUSED,
    TaskStatus.BLOCKED: EventType.TASK_BLOCKED,
    TaskStatus.COMPLETED: EventType.TASK_COMPLETED,
    TaskStatus.FAILED: EventType.TASK_FAILED,
    TaskStatus.CANCELLED: EventType.TASK_CANCELLED,
}

#: Which step event each requested status maps to.
_STEP_EVENT: Dict[StepStatus, EventType] = {
    StepStatus.RUNNING: EventType.STEP_STARTED,
    StepStatus.BLOCKED: EventType.STEP_BLOCKED,
    StepStatus.COMPLETED: EventType.STEP_COMPLETED,
    StepStatus.FAILED: EventType.STEP_FAILED,
    StepStatus.PENDING: EventType.STEP_REOPENED,
    StepStatus.CANCELLED: EventType.STEP_CANCELLED,
}


class TaskNotFound(LookupError):
    """No such task exists **in the caller's scope**.

    Deliberately indistinguishable from "exists but belongs to someone
    else": distinguishing them would turn this error into an existence
    oracle for other users' task ids.
    """


class TaskMemoryService:
    """Command and read facade over an injected task store.

    The service is stateless apart from its injected collaborators, so a
    toolkit may share one instance across turns. Concurrency safety comes
    from the store's per-task serialization plus the optimistic
    ``expected_revision`` check, not from a lock held here.

    Args:
        store: The task store to command. Any implementation of the
            contract will do — the in-memory one and the PostgreSQL one
            are behaviourally identical by construction (AC2).
        config: Capacity and retention configuration.
    """

    def __init__(
        self,
        store: TaskMemoryStore,
        config: Optional[TaskMemoryConfig] = None,
        artifacts: Optional["ArtifactStore"] = None,
    ) -> None:
        """Initialize the service.

        Args:
            store: The injected task store.
            config: Configuration; defaults to :class:`TaskMemoryConfig`.
            artifacts: Artifact store used to validate evidence-bound
                completions. Optional: without it, ``complete_step``
                refuses rather than completing unvalidated. Refusing is
                the safe default — silently accepting a completion whose
                evidence was never checked is exactly the failure this
                feature exists to prevent.
        """
        self._store = store
        self._config = config or TaskMemoryConfig()
        self._artifacts = artifacts

    # ── internals ────────────────────────────────────────────────────

    async def _require(self, scope: TaskScope, task_id: str) -> TaskSnapshot:
        """Load a task or raise, enforcing scope.

        Args:
            scope: The caller's trusted scope.
            task_id: The task to load.

        Returns:
            The snapshot.

        Raises:
            TaskNotFound: If the task does not exist in this scope.
        """
        snapshot = await self._store.load_snapshot(scope, task_id)
        if snapshot is None:
            raise TaskNotFound(f"no task {task_id!r} in this scope")
        return snapshot

    @staticmethod
    def _reject_terminal(state: TaskState) -> None:
        """Refuse ordinary mutation of a finished task.

        Args:
            state: The projection.

        Raises:
            PlanValidationError: If the task is terminal. Create a new
                task for further work; a terminal task is a historical
                record, not a workspace.
        """
        if state.status.is_terminal:
            raise PlanValidationError(
                f"task {state.task_id} is {state.status.value} and accepts no further work; "
                "create a new task instead"
            )

    def _event(
        self,
        task_id: str,
        event_type: EventType,
        payload: Any,
        *,
        turn_id: Optional[str],
        plan_revision: int,
        actor: Actor = Actor.AGENT,
        step_id: Optional[str] = None,
    ) -> JournalEvent:
        """Build one journal event.

        Args:
            task_id: Owning task.
            event_type: The event type.
            payload: Its typed payload.
            turn_id: Conversation turn.
            plan_revision: Plan revision in force.
            actor: Who caused it.
            step_id: Step correlation.

        Returns:
            The event, unsequenced — the store allocates ``seq``.
        """
        return JournalEvent(
            event_id=new_id(),
            task_id=task_id,
            occurred_at=utc_now(),
            event_type=event_type,
            actor=actor,
            turn_id=turn_id,
            plan_revision=plan_revision,
            step_id=step_id,
            payload=payload,
        )

    # ── commands ─────────────────────────────────────────────────────

    async def begin_task(
        self,
        scope: TaskScope,
        *,
        goal: str,
        constraints: Sequence[str] = (),
        steps: Sequence[InitialStepSpec] = (),
        plan_complete: bool = False,
        turn_id: Optional[str] = None,
    ) -> AppendResult:
        """Create a task, with its initial constraints and plan.

        The whole initial plan is validated and its labels resolved
        **before** anything is appended, and the ``task_started`` and
        ``plan_updated`` events are committed together — so there is no
        window in which a task exists with a half-built plan.

        Args:
            scope: Trusted runtime scope.
            goal: What the task is trying to achieve.
            constraints: Standing constraints.
            steps: The initial plan, addressed by request-local labels.
            plan_complete: Whether the plan is already complete.
            turn_id: Conversation turn.

        Returns:
            The append result, whose ``state`` carries the runtime ids
            the caller now needs.

        Raises:
            LimitExceeded: If the scope already holds the maximum number
                of open tasks.
            PlanValidationError: If the initial plan is invalid — a
                duplicate or unknown label, or a dependency cycle.
        """
        page = await self._store.list_tasks(scope, limit=1)
        if page.total_open >= self._config.max_open_tasks_per_scope:
            raise LimitExceeded("open tasks per scope", self._config.max_open_tasks_per_scope, page.total_open)

        task_id = new_id()
        specs, constraint_specs = self._resolve_initial_plan(steps, constraints)

        events: List[JournalEvent] = [
            self._event(
                task_id,
                EventType.TASK_STARTED,
                TaskLifecyclePayload(status=TaskStatus.ACTIVE, goal=goal),
                turn_id=turn_id,
                plan_revision=0,
            )
        ]
        if specs or constraint_specs or plan_complete:
            events.append(
                self._event(
                    task_id,
                    EventType.PLAN_UPDATED,
                    PlanUpdatePayload(
                        added_steps=tuple(specs),
                        added_constraints=tuple(constraint_specs),
                        plan_complete=plan_complete or None,
                        reason="initial plan",
                    ),
                    turn_id=turn_id,
                    plan_revision=0,
                )
            )
        return await self._store.create_task(scope, goal=goal, events=events)

    def _resolve_initial_plan(
        self,
        steps: Sequence[InitialStepSpec],
        constraints: Sequence[str],
    ) -> Tuple[List[PlanStepSpec], List[PlanConstraintSpec]]:
        """Mint runtime ids and resolve request-local labels.

        Args:
            steps: The requested initial steps.
            constraints: The requested constraint texts.

        Returns:
            A ``(step specs, constraint specs)`` pair, with every label
            replaced by the runtime id it refers to.

        Raises:
            LimitExceeded: If the plan or the constraint list is too big.
            PlanValidationError: If a label repeats, a dependency names an
                unknown label, or the resulting graph has a cycle.
        """
        if len(steps) > Limits.MAX_STEPS_PER_TASK:
            raise LimitExceeded("steps", Limits.MAX_STEPS_PER_TASK, len(steps))
        if len(constraints) > Limits.MAX_ACTIVE_CONSTRAINTS:
            raise LimitExceeded("constraints", Limits.MAX_ACTIVE_CONSTRAINTS, len(constraints))

        labels = [s.label for s in steps]
        if len(set(labels)) != len(labels):
            raise PlanValidationError("duplicate step labels in the initial plan")

        by_label: Dict[str, str] = {label: new_id() for label in labels}
        specs: List[PlanStepSpec] = []
        for step in steps:
            unknown = [d for d in step.depends_on_labels if d not in by_label]
            if unknown:
                raise PlanValidationError(f"step {step.label!r} depends on unknown labels: {sorted(unknown)}")
            specs.append(
                PlanStepSpec(
                    step_id=by_label[step.label],
                    title=step.title,
                    description=step.description,
                    required=step.required,
                    depends_on=tuple(by_label[d] for d in step.depends_on_labels),
                    completion_policy=step.completion_policy,
                )
            )

        # Validate the graph BEFORE anything is appended.
        validate_plan_graph(tuple(_as_step(spec) for spec in specs))
        return specs, [PlanConstraintSpec(constraint_id=new_id(), text=text) for text in constraints]

    async def update_plan(
        self,
        scope: TaskScope,
        task_id: str,
        *,
        expected_revision: int,
        changes: PlanChanges,
        reason: Optional[str] = None,
        turn_id: Optional[str] = None,
    ) -> AppendResult:
        """Apply a batch of plan changes under an optimistic revision check.

        The whole batch is validated against the *resulting* plan before
        a single event is written, so a batch that would produce a cycle
        only in combination is still rejected — and rejected without
        mutating anything.

        Args:
            scope: Trusted runtime scope.
            task_id: The task to revise.
            expected_revision: The revision the caller believes is
                current.
            changes: The operations to apply, in order.
            reason: Why the plan is changing.
            turn_id: Conversation turn.

        Returns:
            The append result.

        Raises:
            TaskNotFound: If the task is not in this scope.
            RevisionConflict: If the revision is stale. Nothing changes.
            PlanValidationError: If the batch is invalid. Nothing changes.
        """
        snapshot = await self._require(scope, task_id)
        state = snapshot.state
        self._reject_terminal(state)
        if state.revision != expected_revision:
            raise RevisionConflict(task_id, expected_revision, state.revision)

        payload = self._build_plan_payload(state, changes, reason)
        if payload.is_empty:
            raise PlanValidationError("plan update contains no changes")

        event = self._event(
            task_id, EventType.PLAN_UPDATED, payload, turn_id=turn_id, plan_revision=state.plan_revision
        )
        return await self._store.append_events(scope, task_id, [event], expected_revision=expected_revision)

    def _build_plan_payload(
        self,
        state: TaskState,
        changes: PlanChanges,
        reason: Optional[str],
    ) -> PlanUpdatePayload:
        """Translate a change batch into one validated plan-update payload.

        Args:
            state: The current projection.
            changes: The requested operations.
            reason: Why the plan is changing.

        Returns:
            The payload.

        Raises:
            PlanValidationError: If the batch is structurally invalid.
        """
        by_label: Dict[str, str] = {}
        for change in changes.changes:
            if isinstance(change, AddStep) and change.label is not None:
                by_label[change.label] = new_id()

        added: List[PlanStepSpec] = []
        updated: List[PlanStepPatch] = []
        superseded: List[str] = []
        added_constraints: List[PlanConstraintSpec] = []
        updated_constraints: List[PlanConstraintSpec] = []
        deactivated: List[str] = []
        plan_complete: Optional[bool] = None

        known = set(state.steps_by_id)

        for change in changes.changes:
            if isinstance(change, AddStep):
                step_id = by_label.get(change.label) if change.label else new_id()
                assert step_id is not None
                unknown_labels = [d for d in change.depends_on_labels if d not in by_label]
                if unknown_labels:
                    raise PlanValidationError(f"add_step depends on unknown labels: {sorted(unknown_labels)}")
                unknown_ids = [d for d in change.depends_on if d not in known]
                if unknown_ids:
                    raise PlanValidationError(f"add_step depends on unknown steps: {sorted(unknown_ids)}")
                added.append(
                    PlanStepSpec(
                        step_id=step_id,
                        title=change.title,
                        description=change.description,
                        required=change.required,
                        depends_on=tuple(change.depends_on) + tuple(by_label[d] for d in change.depends_on_labels),
                        completion_policy=change.completion_policy,
                    )
                )
                known.add(step_id)
            elif isinstance(change, UpdateStep):
                if change.step_id not in known:
                    raise PlanValidationError(f"update_step names unknown step {change.step_id!r}")
                updated.append(
                    PlanStepPatch(
                        step_id=change.step_id,
                        title=change.title,
                        description=change.description,
                        required=change.required,
                        depends_on=change.depends_on,
                        completion_policy=change.completion_policy,
                    )
                )
            elif isinstance(change, SupersedeStep):
                if change.step_id not in known:
                    raise PlanValidationError(f"supersede_step names unknown step {change.step_id!r}")
                superseded.append(change.step_id)
            elif isinstance(change, AddConstraint):
                added_constraints.append(PlanConstraintSpec(constraint_id=new_id(), text=change.text))
            elif isinstance(change, UpdateConstraint):
                updated_constraints.append(PlanConstraintSpec(constraint_id=change.constraint_id, text=change.text))
            elif isinstance(change, DeactivateConstraint):
                deactivated.append(change.constraint_id)
            elif isinstance(change, SetPlanComplete):
                plan_complete = change.plan_complete

        self._validate_resulting_plan(state, added, updated, superseded)

        return PlanUpdatePayload(
            added_steps=tuple(added),
            updated_steps=tuple(updated),
            superseded_step_ids=tuple(superseded),
            added_constraints=tuple(added_constraints),
            updated_constraints=tuple(updated_constraints),
            deactivated_constraint_ids=tuple(deactivated),
            plan_complete=plan_complete,
            reason=reason,
        )

    @staticmethod
    def _validate_resulting_plan(
        state: TaskState,
        added: Sequence[PlanStepSpec],
        updated: Sequence[PlanStepPatch],
        superseded: Sequence[str],
    ) -> None:
        """Validate the plan the batch would produce.

        Checking the *result* rather than each operation is what catches
        a cycle that only two changes together would create.

        Args:
            state: The current projection.
            added: Steps the batch adds.
            updated: Patches the batch applies.
            superseded: Steps the batch retires.

        Raises:
            PlanValidationError: If the resulting plan is invalid, or a
                patch would edit a completed step's criteria in place.
        """
        steps = list(state.steps)
        index = {s.step_id: i for i, s in enumerate(steps)}

        for spec in added:
            if spec.step_id in index:
                raise PlanValidationError(f"step {spec.step_id} already exists")
            steps.append(_as_step(spec))
            index[spec.step_id] = len(steps) - 1

        for patch in updated:
            current = steps[index[patch.step_id]]
            if current.status is StepStatus.COMPLETED and (
                patch.completion_policy is not None or patch.depends_on is not None
            ):
                raise PlanValidationError(
                    f"step {patch.step_id} is completed; reopen it before changing its " "criteria or inputs"
                )
            update: Dict[str, Any] = {}
            if patch.depends_on is not None:
                update["depends_on"] = patch.depends_on
            if patch.completion_policy is not None:
                update["completion_policy"] = patch.completion_policy
            if update:
                steps[index[patch.step_id]] = current.model_copy(update=update)

        for step_id in superseded:
            steps[index[step_id]] = steps[index[step_id]].model_copy(update={"status": StepStatus.SUPERSEDED})

        validate_plan_graph(tuple(steps))

    async def update_step(
        self,
        scope: TaskScope,
        task_id: str,
        step_id: str,
        *,
        expected_revision: int,
        status: StepStatus,
        evidence_refs: Sequence[EvidenceRef] = (),
        note: Optional[str] = None,
        reason: Optional[str] = None,
        completion_source: Optional[CompletionSource] = None,
        validator_results: Sequence[Tuple[str, bool]] = (),
        turn_id: Optional[str] = None,
    ) -> AppendResult:
        """Record a step transition.

        This module records what was decided; it does **not** decide
        whether the evidence justifies a completion. That judgement is the
        completion validators' (TASK-2980), which supply
        ``completion_source`` and ``validator_results`` here.

        Args:
            scope: Trusted runtime scope.
            task_id: The owning task.
            step_id: The step to transition.
            expected_revision: The revision the caller believes is
                current.
            status: The status to move to.
            evidence_refs: Exact artifact versions to bind.
            note: Completion or transition note.
            reason: Why it blocked or failed.
            completion_source: How it was completed, when it was.
            validator_results: Recorded validator outcomes, consumed by
                replay rather than re-run.
            turn_id: Conversation turn.

        Returns:
            The append result.

        Raises:
            TaskNotFound: If the task is not in this scope.
            RevisionConflict: If the revision is stale.
            PlanValidationError: If the step is unknown, the status is
                not a legal target, or a bare alias was passed as
                evidence.
        """
        snapshot = await self._require(scope, task_id)
        state = snapshot.state
        self._reject_terminal(state)
        if state.revision != expected_revision:
            raise RevisionConflict(task_id, expected_revision, state.revision)
        if step_id not in state.steps_by_id:
            raise PlanValidationError(f"unknown step {step_id!r}")
        if status is StepStatus.SUPERSEDED:
            raise PlanValidationError("a step is superseded by a plan change, not by a step update")

        event = self._event(
            task_id,
            _STEP_EVENT[status],
            StepPayload(
                step_id=step_id,
                status=status,
                evidence_refs=tuple(evidence_refs),
                completion_source=completion_source,
                note=note,
                reason=reason,
                validator_results=tuple(validator_results),
            ),
            turn_id=turn_id,
            plan_revision=state.plan_revision,
            step_id=step_id,
        )
        return await self._store.append_events(scope, task_id, [event], expected_revision=expected_revision)

    async def update_task(
        self,
        scope: TaskScope,
        task_id: str,
        *,
        expected_revision: int,
        status: TaskStatus,
        reason: Optional[str] = None,
        turn_id: Optional[str] = None,
        actor: Actor = Actor.AGENT,
    ) -> AppendResult:
        """Move a task through its lifecycle.

        Pause, resume, block, fail, cancel and complete all go through
        the same event rules — completion in particular is still gated by
        the reducer, which refuses it while the plan is incomplete or a
        required step is unfinished.

        Args:
            scope: Trusted runtime scope.
            task_id: The task to transition.
            expected_revision: The revision the caller believes is
                current.
            status: The status to move to.
            reason: Why.
            turn_id: Conversation turn.
            actor: Who is acting — the sweeper uses this for retention
                transitions.

        Returns:
            The append result.

        Raises:
            TaskNotFound: If the task is not in this scope.
            RevisionConflict: If the revision is stale.
            PlanValidationError: If the task is already terminal.
        """
        snapshot = await self._require(scope, task_id)
        state = snapshot.state
        self._reject_terminal(state)
        if state.revision != expected_revision:
            raise RevisionConflict(task_id, expected_revision, state.revision)

        event = self._event(
            task_id,
            _STATUS_EVENT[status],
            TaskLifecyclePayload(status=status, reason=reason),
            turn_id=turn_id,
            plan_revision=state.plan_revision,
            actor=actor,
        )
        return await self._store.append_events(scope, task_id, [event], expected_revision=expected_revision)

    async def record_decision(
        self,
        scope: TaskScope,
        task_id: str,
        *,
        text: str,
        reason: str = "",
        affected_step_ids: Sequence[str] = (),
        expected_revision: Optional[int] = None,
        turn_id: Optional[str] = None,
    ) -> Tuple[AppendResult, str]:
        """Record a decision against a task.

        Args:
            scope: Trusted runtime scope.
            task_id: The owning task.
            text: What was decided.
            reason: Why.
            affected_step_ids: Steps the decision bears on.
            expected_revision: Optional optimistic check. A decision does
                not conflict with concurrent work, so this is optional
                where a plan change's is not.
            turn_id: Conversation turn.

        Returns:
            A ``(result, decision_id)`` pair.

        Raises:
            TaskNotFound: If the task is not in this scope.
            RevisionConflict: If a supplied revision is stale.
            PlanValidationError: If an affected step is unknown.
        """
        snapshot = await self._require(scope, task_id)
        state = snapshot.state
        self._reject_terminal(state)
        if expected_revision is not None and state.revision != expected_revision:
            raise RevisionConflict(task_id, expected_revision, state.revision)

        unknown = [s for s in affected_step_ids if s not in state.steps_by_id]
        if unknown:
            raise PlanValidationError(f"decision affects unknown steps: {sorted(unknown)}")

        decision_id = new_id()
        event = self._event(
            task_id,
            EventType.DECISION_RECORDED,
            DecisionPayload(
                decision_id=decision_id,
                text=text,
                reason=reason,
                affected_step_ids=tuple(affected_step_ids),
            ),
            turn_id=turn_id,
            plan_revision=state.plan_revision,
        )
        result = await self._store.append_events(scope, task_id, [event], expected_revision=expected_revision)
        return result, decision_id

    async def set_resume_hint(
        self,
        scope: TaskScope,
        task_id: str,
        *,
        next_action: str,
        step_id: Optional[str] = None,
        turn_id: Optional[str] = None,
    ) -> AppendResult:
        """Record what to do next.

        The hint's ``stale`` flag is **derived** by the reducer from later
        events; it is never authored here.

        Args:
            scope: Trusted runtime scope.
            task_id: The owning task.
            next_action: The next action.
            step_id: The step it refers to.
            turn_id: Conversation turn.

        Returns:
            The append result.

        Raises:
            TaskNotFound: If the task is not in this scope.
            PlanValidationError: If ``step_id`` is unknown.
        """
        snapshot = await self._require(scope, task_id)
        state = snapshot.state
        self._reject_terminal(state)
        if step_id is not None and step_id not in state.steps_by_id:
            raise PlanValidationError(f"resume hint names unknown step {step_id!r}")

        event = self._event(
            task_id,
            EventType.RESUME_HINT_UPDATED,
            ResumeHintPayload(text=next_action, step_id=step_id),
            turn_id=turn_id,
            plan_revision=state.plan_revision,
            step_id=step_id,
        )
        return await self._store.append_events(scope, task_id, [event])

    async def complete_step(
        self,
        scope: TaskScope,
        task_id: str,
        step_id: str,
        *,
        expected_revision: int,
        evidence_refs: Sequence[EvidenceRef] = (),
        note: Optional[str] = None,
        turn_id: Optional[str] = None,
        max_attempts: int = 2,
    ) -> AppendResult:
        """Complete a step, but only if its evidence supports it.

        This is the evidence-bound path. Validation runs **outside** the
        store's lock — validators may do real work, and holding a lock
        across them would serialize the whole task on the slowest check.
        The result is then committed against the same task revision and
        the same evidence fingerprints it validated; if either moved, the
        attempt is discarded and retried rather than committing a stale
        completion.

        Args:
            scope: Trusted runtime scope.
            task_id: The owning task.
            step_id: The step to complete.
            expected_revision: The revision the caller believes is
                current.
            evidence_refs: Exact artifact versions offered as evidence.
            note: The completion note.
            turn_id: Conversation turn.
            max_attempts: How many times to revalidate when the task
                moves underneath the validation.

        Returns:
            The append result.

        Raises:
            CompletionValidationError: If the evidence does not support
                the completion. The step is left exactly as it was.
            EvidenceMutated: If content changed behind a bound version.
                This is not an ordinary refusal — anything already
                completed against that version must be reopened.
            UnknownValidatorError: If the policy names an unregistered
                validator.
            RevisionConflict: If the task kept moving across every
                attempt.
        """
        if self._artifacts is None:
            raise CompletionValidationError(
                "completion validation requires an artifact store; refusing to complete "
                "a step whose evidence cannot be checked"
            )

        revision = expected_revision
        last_conflict: Optional[RevisionConflict] = None

        for _ in range(max(1, max_attempts)):
            snapshot = await self._require(scope, task_id)
            state = snapshot.state
            self._reject_terminal(state)
            if state.revision != revision:
                raise RevisionConflict(task_id, revision, state.revision)

            outcome = await validate_completion(
                self._artifacts,
                scope,
                state,
                step_id,
                evidence_refs=evidence_refs,
                note=note,
            )
            if not outcome.passed:
                raise CompletionValidationError(f"step {step_id} cannot complete: " + "; ".join(outcome.failures))

            # Capture the fingerprints validation actually saw, ONCE, so
            # the commit-time re-check compares against those rather than
            # re-reading and comparing a value with itself.
            validated_fingerprints: List[Optional[str]] = []
            for ref in outcome.bound:
                descriptor = await self._artifacts.get_version(scope, ref, task_id=task_id)
                validated_fingerprints.append(descriptor.fingerprint if descriptor else None)

            # Re-check what validation depended on, now that it is done.
            fresh = await self._require(scope, task_id)
            try:
                await assert_unchanged(
                    self._artifacts,
                    scope,
                    task_id=task_id,
                    validated_revision=state.revision,
                    current_revision=fresh.state.revision,
                    bound=outcome.bound,
                    fingerprints=validated_fingerprints,
                )
            except RevisionConflict as conflict:
                # The task moved while we validated. Revalidate against
                # the new state rather than committing what we checked
                # against the old one.
                last_conflict = conflict
                revision = fresh.state.revision
                continue

            return await self.update_step(
                scope,
                task_id,
                step_id,
                expected_revision=state.revision,
                status=StepStatus.COMPLETED,
                evidence_refs=outcome.bound,
                note=note,
                completion_source=outcome.source,
                validator_results=outcome.results,
                turn_id=turn_id,
            )

        assert last_conflict is not None
        raise last_conflict

    # ── reads ────────────────────────────────────────────────────────

    async def get_task(self, scope: TaskScope, task_id: str) -> TaskSnapshot:
        """Load one task's projection.

        Args:
            scope: Trusted runtime scope.
            task_id: The task to load.

        Returns:
            The snapshot.

        Raises:
            TaskNotFound: If the task is not in this scope.
        """
        return await self._require(scope, task_id)

    async def list_open_tasks(self, scope: TaskScope, *, limit: int = 20) -> TaskPage:
        """List the scope's open tasks.

        Args:
            scope: Trusted runtime scope.
            limit: Bounded page size.

        Returns:
            A bounded page of summaries.
        """
        return await self._store.list_tasks(scope, limit=limit)

    async def compact_state(self, scope: TaskScope, task_id: str) -> Dict[str, Any]:
        """Return the small state summary a command result carries.

        Deliberately tiny: a command's acknowledgement should let the
        caller issue its next command, not re-deliver the whole task.

        Args:
            scope: Trusted runtime scope.
            task_id: The task to summarize.

        Returns:
            A JSON-safe summary.

        Raises:
            TaskNotFound: If the task is not in this scope.
        """
        state = (await self._require(scope, task_id)).state
        summary: Dict[str, Any] = {
            "task_id": state.task_id,
            "status": state.status.value,
            "revision": state.revision,
            "plan_revision": state.plan_revision,
            "plan_complete": state.plan_complete,
            "ready_step_ids": list(state.ready_step_ids),
            "active_step_ids": list(state.active_step_ids),
        }
        if not state.plan_complete:
            summary["plan_incomplete"] = True
        return summary


def _as_step(spec: PlanStepSpec):
    """Build the step a :class:`PlanStepSpec` describes, for validation only.

    Args:
        spec: The specification.

    Returns:
        A :class:`TaskStep` used solely to validate the resulting graph.
    """
    from .models import TaskStep

    return TaskStep(
        step_id=spec.step_id,
        title=spec.title,
        description=spec.description,
        required=spec.required,
        depends_on=spec.depends_on,
        completion_policy=spec.completion_policy,
    )
