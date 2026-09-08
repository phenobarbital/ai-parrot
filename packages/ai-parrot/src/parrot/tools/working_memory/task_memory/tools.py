"""The ten LLM-facing task-memory tools (FEAT-538, spec §2).

Two things live here:

:class:`TaskMemory`
    The composition root the toolkit holds privately — config, scope,
    stores, service, recall reader, and the currently selected task. It
    is *not* a tool and is never exposed to a model.

:class:`TaskMemoryToolsMixin`
    The ten public async methods the toolkit's existing ``wm`` prefix
    turns into ``wm_begin_task``, ``wm_update_plan``, and so on. Python
    method names omit the prefix; ``_resolve_tool_name`` adds it.

Every one of these is **hidden entirely when task memory is disabled**:
the toolkit appends :data:`TASK_TOOL_METHODS` to ``exclude_tools``, which
``_generate_tools`` already honours. A disabled deployment therefore
publishes exactly the tool set it always did (AC13).

Three rules that shape the code below:

- **Reads never mutate.** Recall and the two listing tools append no
  journal events and — importantly — never *implicitly select* a task.
  Selecting as a side effect of reading would make a read silently
  change what every later command means (AC10).
- **An omitted task id resolves only from the authoritative selected
  association** (spec §2). With several open tasks and no selection the
  answer is ``needs_task_selection`` plus a bounded page to choose from.
  Never similarity, never "the most recent one". Only ``wm_recall_task``
  accepts an omitted id at all; every command requires an explicit one.
- **Failures are returned as typed data, not raised.** A model reacts to
  a structured answer far better than to a traceback, and the ``error``
  discriminator is what tells it whether to retry, re-read, or stop.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError

from parrot.tools.decorators import tool_schema

from .config import TaskMemoryConfig
from .context import current_session
from .models import (
    CompletionPolicy,
    EvidenceRef,
    InitialStepSpec,
    LimitExceeded,
    Limits,
    PlanChanges,
    PlanValidationError,
    RevisionConflict,
    ScopeViolation,
    StepStatus,
    TaskMemoryError,
    TaskScope,
    TaskStatus,
)
from .recall import MAX_RECALL_TOKENS, MAX_RECENT_CALLS, RecallReader, RecallStatus
from .service import TaskMemoryService, TaskNotFound
from .validators import CompletionValidationError, EvidenceMutated

__all__ = (
    "TASK_TOOL_METHODS",
    "TaskMemory",
    "TaskMemoryToolsMixin",
    "BeginTaskInput",
    "UpdatePlanInput",
    "UpdateStepInput",
    "RecordDecisionInput",
    "SetResumeHintInput",
    "RecallTaskInput",
    "ListTaskEventsInput",
    "ListTaskArtifactsInput",
    "SelectTaskInput",
    "UpdateTaskInput",
)

logger = logging.getLogger(__name__)

#: The public method names this mixin contributes, i.e. exactly the ten
#: tools of spec §2 with the ``wm_`` prefix stripped. The toolkit excludes
#: precisely these when task memory is disabled.
#:
#: Kept as data rather than derived by introspection on purpose: a derived
#: list would silently start exposing any helper that later became public,
#: which is the failure mode AC13 exists to prevent.
TASK_TOOL_METHODS: tuple = (
    "begin_task",
    "update_plan",
    "update_step",
    "record_decision",
    "set_resume_hint",
    "recall_task",
    "list_task_events",
    "list_task_artifacts",
    "select_task",
    "update_task",
)


class TaskMemory:
    """Private composition root for a task-memory-enabled toolkit.

    Deliberately not a tool and never exposed to a model. It bundles the
    collaborators the toolkit needs and owns the selected-task
    association.

    Selection is read through the turn session when one is bound, so a
    selection made inside a turn is visible to every child task and
    thread of that turn — the same reason the session holds its
    declaration registry by reference rather than in a ContextVar.

    Args:
        store: The task store.
        artifacts: The artifact store.
        scope: Trusted runtime scope. Never taken from a tool argument.
        config: Configuration; defaults to :class:`TaskMemoryConfig`.
        association: Optional durable association store. Without one the
            selection is in-process only — which is all Delivery A
            claims, and is why it must never be advertised as durable.
        cache: Optional recall cache.
        omission_store: Optional omission store for recall to probe.
    """

    def __init__(
        self,
        store: Any,
        artifacts: Any,
        scope: TaskScope,
        config: Optional[TaskMemoryConfig] = None,
        *,
        association: Any = None,
        cache: Any = None,
        omission_store: Any = None,
    ) -> None:
        """Initialize the composition root."""
        self.store = store
        self.artifacts = artifacts
        self.scope = scope
        self.config = config or TaskMemoryConfig()
        self.association = association
        self.service = TaskMemoryService(store, self.config, artifacts=artifacts)
        self._selected: Optional[str] = None
        self.reader = RecallReader(
            store,
            artifacts,
            config=self.config,
            cache=cache,
            association=association,
            omission_store=omission_store,
        )

    @property
    def session(self) -> Any:
        """The turn session bound to this context, or ``None``."""
        return current_session()

    @property
    def task_id(self) -> Optional[str]:
        """The selected task id, or ``None``.

        Prefers the turn session's selection: it is the object every
        concurrent branch of a turn shares, so while a turn is in
        progress it is the authoritative answer.
        """
        session = self.session
        if session is not None and session.task_id is not None:
            return session.task_id
        return self._selected

    def select(self, task_id: Optional[str]) -> None:
        """Record the selected task on both the toolkit and the turn.

        In-process only. Persisting to the durable association is a
        separate, awaitable step (:meth:`persist_selection`) because it
        does I/O and can fail — and a failure there must not look like a
        failure to select.

        Args:
            task_id: The task to select, or ``None`` to clear.
        """
        self._selected = task_id
        session = self.session
        if session is not None:
            session.select_task(task_id)

    async def persist_selection(self, task_id: str, *, new_task: bool = False) -> bool:
        """Record the selection in the durable association, if one is wired.

        Args:
            task_id: The committed task to associate.
            new_task: Whether this is a freshly created task, which must
                also join the open set.

        Returns:
            ``True`` when the association is authoritative, ``False``
            when it is degraded or absent. A ``False`` here is never a
            reason to refuse the command: the task is already committed,
            and the caller must be able to recover it rather than create
            a second one.
        """
        if self.association is None:
            return False
        try:
            if new_task:
                result = await self.association.associate(self.scope, task_id, select=True)
            else:
                result = await self.association.select(self.scope, task_id)
        except Exception:  # noqa: BLE001 - association loss must not lose the task
            logger.warning("task-memory association write failed for %s", task_id, exc_info=True)
            return False
        return not result.degraded

    async def release_selection(self, task_id: str) -> None:
        """Remove a finished task from the durable open set, if one is wired.

        Args:
            task_id: The task that reached a terminal status.
        """
        if self.association is None:
            return
        try:
            await self.association.close_task(self.scope, task_id)
        except Exception:  # noqa: BLE001 - a stale open entry is recoverable
            logger.warning("task-memory association close failed for %s", task_id, exc_info=True)


# ─────────────────────────────────────────────────────────────
# Input schemas (spec §2 New Public Interfaces)
# ─────────────────────────────────────────────────────────────


class _StepSpecInput(BaseModel):
    """One step of an initial plan, addressed by a request-local label."""

    label: str = Field(
        max_length=Limits.MAX_IDENTIFIER,
        description="Request-local label, unique in this call, so steps can depend on each other before ids exist",
    )
    title: str = Field(max_length=Limits.MAX_STEP_TITLE, description="Short step title")
    description: str = Field(default="", max_length=Limits.MAX_STEP_DESCRIPTION)
    required: bool = Field(default=True, description="Whether the task can complete without this step")
    depends_on_labels: List[str] = Field(default_factory=list, description="Labels of steps this one depends on")


class BeginTaskInput(BaseModel):
    """Input for ``wm_begin_task``."""

    goal: str = Field(max_length=Limits.MAX_GOAL, description="What this task must achieve")
    constraints: List[str] = Field(default_factory=list, description="Standing constraints that apply throughout")
    steps: List[_StepSpecInput] = Field(default_factory=list, description="Initial plan")
    plan_complete: bool = Field(default=False, description="Whether the plan is already complete")


class UpdatePlanInput(BaseModel):
    """Input for ``wm_update_plan``."""

    task_id: str = Field(max_length=Limits.MAX_IDENTIFIER, description="Task to revise")
    expected_revision: int = Field(ge=0, description="The revision you believe is current")
    changes: List[dict] = Field(
        description=(
            "Operations to apply, in order. Each carries an 'op' of: add_step, update_step, "
            "supersede_step, add_constraint, update_constraint, deactivate_constraint, "
            "set_plan_complete."
        ),
    )
    reason: Optional[str] = Field(default=None, max_length=Limits.MAX_REASON, description="Why the plan is changing")


class UpdateStepInput(BaseModel):
    """Input for ``wm_update_step``."""

    task_id: str = Field(max_length=Limits.MAX_IDENTIFIER)
    step_id: str = Field(max_length=Limits.MAX_IDENTIFIER)
    expected_revision: int = Field(ge=0, description="The revision you believe is current")
    status: str = Field(description="One of: pending, running, blocked, completed, failed, cancelled, superseded")
    evidence_refs: List[str] = Field(
        default_factory=list,
        description="Exact artifact versions as 'artifact_id@version'. A bare alias is rejected.",
    )
    note: Optional[str] = Field(default=None, max_length=Limits.MAX_REASON, description="Completion or transition note")
    reason: Optional[str] = Field(default=None, max_length=Limits.MAX_REASON, description="Why it blocked or failed")


class RecordDecisionInput(BaseModel):
    """Input for ``wm_record_decision``."""

    task_id: str = Field(max_length=Limits.MAX_IDENTIFIER)
    text: str = Field(max_length=Limits.MAX_DECISION_TEXT, description="What was decided")
    reason: str = Field(default="", max_length=Limits.MAX_DECISION_TEXT, description="Why")
    affected_step_ids: List[str] = Field(default_factory=list, description="Steps the decision bears on")


class SetResumeHintInput(BaseModel):
    """Input for ``wm_set_resume_hint``."""

    task_id: str = Field(max_length=Limits.MAX_IDENTIFIER)
    next_action: str = Field(max_length=Limits.MAX_HINT_TEXT, description="What to do next")
    step_id: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)


class RecallTaskInput(BaseModel):
    """Input for ``wm_recall_task``."""

    task_id: Optional[str] = Field(
        default=None,
        max_length=Limits.MAX_IDENTIFIER,
        description="Task to recall. Omit to use the selected task; never inferred by similarity.",
    )
    max_tokens: int = Field(default=2500, ge=1, le=MAX_RECALL_TOKENS, description="Budget for the snapshot")
    recent_calls_limit: int = Field(default=8, ge=0, le=MAX_RECENT_CALLS)


class ListTaskEventsInput(BaseModel):
    """Input for ``wm_list_task_events``."""

    task_id: str = Field(max_length=Limits.MAX_IDENTIFIER)
    after_seq: int = Field(default=0, ge=0, description="Return events strictly after this sequence")
    limit: int = Field(default=50, ge=1, le=200)


class ListTaskArtifactsInput(BaseModel):
    """Input for ``wm_list_task_artifacts``."""

    task_id: str = Field(max_length=Limits.MAX_IDENTIFIER)
    limit: int = Field(default=50, ge=1, le=200)
    cursor: Optional[str] = Field(default=None, max_length=Limits.MAX_CURSOR, description="Cursor from a previous page")


class SelectTaskInput(BaseModel):
    """Input for ``wm_select_task``."""

    task_id: str = Field(max_length=Limits.MAX_IDENTIFIER, description="Task to select for this session")


class UpdateTaskInput(BaseModel):
    """Input for ``wm_update_task``."""

    task_id: str = Field(max_length=Limits.MAX_IDENTIFIER)
    expected_revision: int = Field(ge=0, description="The revision you believe is current")
    status: str = Field(description="One of: active, paused, blocked, completed, failed, cancelled")
    reason: Optional[str] = Field(default=None, max_length=Limits.MAX_REASON)


# ─────────────────────────────────────────────────────────────
# The mixin
# ─────────────────────────────────────────────────────────────


def _error(kind: str, message: str, **extra: Any) -> Dict[str, Any]:
    """Build a compact, typed error response.

    Args:
        kind: Machine-readable discriminator the model can branch on.
        message: Human-readable explanation.
        **extra: Additional typed fields.

    Returns:
        The response.
    """
    return {"status": "error", "error": kind, "message": message, **extra}


class TaskMemoryToolsMixin:
    """The ten task-memory tools, mixed into the working-memory toolkit.

    Every method assumes ``self._task_memory`` is a :class:`TaskMemory`.
    The toolkit hides all of them when it is ``None``, so they are
    unreachable in a disabled deployment.
    """

    _task_memory: Optional[TaskMemory]

    # ── internals ────────────────────────────────────────────────────

    def _tm(self) -> TaskMemory:
        """Return the composition root.

        Returns:
            The task memory.

        Raises:
            RuntimeError: If called while disabled — which the toolkit's
                tool hiding should already have made impossible.
        """
        tm = self._task_memory
        if tm is None:  # pragma: no cover - defensive; these tools are hidden
            raise RuntimeError("task memory is not configured for this toolkit")
        return tm

    # ── commands ─────────────────────────────────────────────────────

    @tool_schema(BeginTaskInput)
    async def begin_task(
        self,
        goal: str,
        constraints: Optional[List[str]] = None,
        steps: Optional[List[dict]] = None,
        plan_complete: bool = False,
    ) -> dict:
        """Start a new task with a goal, constraints and an initial plan.

        Use this before multi-step work you may need to resume after
        losing conversational context. The new task becomes the selected
        one, so later commands can address it without repeating its id.

        Args:
            goal: What this task must achieve.
            constraints: Standing constraints that apply throughout.
            steps: Initial plan. Each step carries a request-local
                ``label``, a ``title``, and optional
                ``depends_on_labels`` referring to other labels here.
            plan_complete: Whether the plan is already complete. A task
                cannot complete while its plan is not.

        Returns:
            The runtime task and step ids, the revision, and a compact
            state summary.
        """
        tm = self._tm()
        try:
            specs = [
                InitialStepSpec(
                    label=s["label"],
                    title=s["title"],
                    description=s.get("description", ""),
                    required=s.get("required", True),
                    depends_on_labels=tuple(s.get("depends_on_labels", ())),
                    completion_policy=CompletionPolicy(),
                )
                for s in (steps or [])
            ]
        except (KeyError, ValidationError, TaskMemoryError) as exc:
            return _error("plan_invalid", f"malformed step specification: {exc}")

        try:
            result = await tm.service.begin_task(
                tm.scope,
                goal=goal,
                constraints=tuple(constraints or ()),
                steps=specs,
                plan_complete=plan_complete,
            )
        except PlanValidationError as exc:
            return _error("plan_invalid", str(exc))
        except LimitExceeded as exc:
            return _error("limit_exceeded", str(exc), field=exc.field, limit=exc.limit)

        # Selected only AFTER the append commits, so a rejected creation
        # never leaves a selection pointing at a task that does not exist.
        tm.select(result.state.task_id)
        associated = await tm.persist_selection(result.state.task_id, new_task=True)
        return {
            "status": "started",
            "association_durable": associated,
            "task_id": result.state.task_id,
            "revision": result.state.revision,
            "steps": [{"step_id": s.step_id, "title": s.title} for s in result.state.steps],
            "state": await tm.service.compact_state(tm.scope, result.state.task_id),
        }

    @tool_schema(UpdatePlanInput)
    async def update_plan(
        self,
        task_id: str,
        expected_revision: int,
        changes: List[dict],
        reason: Optional[str] = None,
    ) -> dict:
        """Revise a task's plan: add, update or retire steps and constraints.

        The whole batch is validated before anything is written, so a set
        of changes that would only produce a cycle in combination is
        rejected without mutating the plan.

        Args:
            task_id: Task to revise.
            expected_revision: The revision you believe is current. A
                mismatch is reported with the current state rather than
                silently overwriting someone else's work.
            changes: Operations to apply, in order. Each is discriminated
                by its ``op`` field.
            reason: Why the plan is changing.

        Returns:
            The new revision and compact state, or a typed conflict.
        """
        tm = self._tm()
        try:
            # The union is discriminated on ``op``, so validating the raw
            # list here is both the parse and the "is this a real
            # operation?" check — no hand-written dispatch to drift out
            # of step with the model definitions.
            batch = PlanChanges.model_validate({"changes": changes})
        except (ValidationError, TaskMemoryError) as exc:
            return _error("plan_invalid", str(exc))

        try:
            result = await tm.service.update_plan(
                tm.scope, task_id, expected_revision=expected_revision, changes=batch, reason=reason
            )
        except RevisionConflict as exc:
            return _error(
                "revision_conflict",
                str(exc),
                expected=exc.expected,
                current=exc.current,
                state=await tm.service.compact_state(tm.scope, task_id),
            )
        except (TaskNotFound, ScopeViolation) as exc:
            return _error("task_not_found", str(exc))
        except PlanValidationError as exc:
            return _error("plan_invalid", str(exc))
        except LimitExceeded as exc:
            return _error("limit_exceeded", str(exc), field=exc.field, limit=exc.limit)

        return {
            "status": "updated",
            "revision": result.state.revision,
            "plan_revision": result.state.plan_revision,
            "state": await tm.service.compact_state(tm.scope, task_id),
        }

    @tool_schema(UpdateStepInput)
    async def update_step(
        self,
        task_id: str,
        step_id: str,
        expected_revision: int,
        status: str,
        evidence_refs: Optional[List[str]] = None,
        note: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> dict:
        """Move a step to a new status, optionally binding evidence.

        Completing a step goes through evidence validation: the refs you
        give are resolved to exact artifact versions and checked. A tool
        call that merely succeeded is never on its own evidence that a
        step is done.

        Args:
            task_id: Owning task.
            step_id: Step to transition.
            expected_revision: The revision you believe is current.
            status: Target status.
            evidence_refs: Exact ``artifact_id@version`` references.
            note: Completion or transition note.
            reason: Why it blocked or failed.

        Returns:
            The accepted transition, or a typed validation failure.
        """
        tm = self._tm()
        try:
            step_status = StepStatus(status)
        except ValueError:
            return _error("invalid_status", f"unknown step status {status!r}")

        try:
            refs = tuple(EvidenceRef.parse(r) for r in (evidence_refs or ()))
        except (ValueError, TaskMemoryError) as exc:
            return _error("bare_alias", str(exc))

        try:
            if step_status is StepStatus.COMPLETED:
                # The evidence-bound path, never the plain transition:
                # that one only records a judgement made elsewhere.
                result = await tm.service.complete_step(
                    tm.scope,
                    task_id,
                    step_id,
                    expected_revision=expected_revision,
                    evidence_refs=refs,
                    note=note,
                )
            else:
                result = await tm.service.update_step(
                    tm.scope,
                    task_id,
                    step_id,
                    expected_revision=expected_revision,
                    status=step_status,
                    evidence_refs=refs,
                    note=note,
                    reason=reason,
                )
        except RevisionConflict as exc:
            return _error("revision_conflict", str(exc), expected=exc.expected, current=exc.current)
        except EvidenceMutated as exc:
            return _error("evidence_mutated", str(exc), ref=str(exc.ref))
        except CompletionValidationError as exc:
            return _error("completion_refused", str(exc))
        except (TaskNotFound, ScopeViolation) as exc:
            return _error("task_not_found", str(exc))
        except PlanValidationError as exc:
            return _error("invalid_transition", str(exc))
        except LimitExceeded as exc:
            return _error("limit_exceeded", str(exc), field=exc.field, limit=exc.limit)

        step = result.state.steps_by_id[step_id]
        # A step that just started running is published to the turn
        # session so subsequent tool dispatches attribute to it. Only
        # after the append committed: declaring a step whose transition
        # was rejected would attribute later work to something that is
        # not actually running.
        if step_status is StepStatus.RUNNING:
            session = tm.session
            if session is not None:
                session.declare(step_id)

        return {
            "status": "updated",
            "revision": result.state.revision,
            "step": {
                "step_id": step.step_id,
                "status": step.status.value,
                "completion_source": step.completion_source.value if step.completion_source else None,
                "evidence": [str(r) for r in step.evidence_refs],
            },
        }

    @tool_schema(RecordDecisionInput)
    async def record_decision(
        self,
        task_id: str,
        text: str,
        reason: str = "",
        affected_step_ids: Optional[List[str]] = None,
    ) -> dict:
        """Record a decision so it survives losing conversational context.

        Args:
            task_id: Owning task.
            text: What was decided.
            reason: Why.
            affected_step_ids: Steps the decision bears on.

        Returns:
            The decision id and the new revision.
        """
        tm = self._tm()
        try:
            result, decision_id = await tm.service.record_decision(
                tm.scope,
                task_id,
                text=text,
                reason=reason,
                affected_step_ids=tuple(affected_step_ids or ()),
            )
        except (TaskNotFound, ScopeViolation) as exc:
            return _error("task_not_found", str(exc))
        except PlanValidationError as exc:
            return _error("invalid_reference", str(exc))
        except LimitExceeded as exc:
            return _error("limit_exceeded", str(exc), field=exc.field, limit=exc.limit)
        return {"status": "recorded", "decision_id": decision_id, "revision": result.state.revision}

    @tool_schema(SetResumeHintInput)
    async def set_resume_hint(self, task_id: str, next_action: str, step_id: Optional[str] = None) -> dict:
        """Record what to do next, for whoever resumes this task.

        Args:
            task_id: Owning task.
            next_action: The next action to take.
            step_id: The step it refers to.

        Returns:
            The saved hint and the new revision.
        """
        tm = self._tm()
        try:
            result = await tm.service.set_resume_hint(tm.scope, task_id, next_action=next_action, step_id=step_id)
        except (TaskNotFound, ScopeViolation) as exc:
            return _error("task_not_found", str(exc))
        except PlanValidationError as exc:
            return _error("invalid_reference", str(exc))
        except LimitExceeded as exc:
            return _error("limit_exceeded", str(exc), field=exc.field, limit=exc.limit)
        return {"status": "saved", "revision": result.state.revision, "hint": next_action}

    @tool_schema(SelectTaskInput)
    async def select_task(self, task_id: str) -> dict:
        """Select which task subsequent commands and recall apply to.

        This is the explicit repair for a lost association. Recall never
        selects a task for you and never guesses one by similarity, so
        this tool is the only way to re-point the session.

        Args:
            task_id: Task to select. Validated to exist in this scope
                before the association is changed.

        Returns:
            The validated selection and a compact state summary.
        """
        tm = self._tm()
        try:
            snapshot = await tm.service.get_task(tm.scope, task_id)
        except (TaskNotFound, ScopeViolation) as exc:
            return _error("task_not_found", str(exc))

        tm.select(snapshot.state.task_id)
        associated = await tm.persist_selection(snapshot.state.task_id)
        return {
            "status": "selected",
            "task_id": snapshot.state.task_id,
            "association_durable": associated,
            "state": await tm.service.compact_state(tm.scope, snapshot.state.task_id),
        }

    @tool_schema(UpdateTaskInput)
    async def update_task(
        self, task_id: str, expected_revision: int, status: str, reason: Optional[str] = None
    ) -> dict:
        """Pause, resume, block, fail, cancel or complete a task.

        Completion is gated by the reducer: a task completes only once
        its plan is declared complete and every required step is done.

        Args:
            task_id: Task to transition.
            expected_revision: The revision you believe is current.
            status: Target status.
            reason: Why.

        Returns:
            The new status and revision, or a typed refusal.
        """
        tm = self._tm()
        try:
            task_status = TaskStatus(status)
        except ValueError:
            return _error("invalid_status", f"unknown task status {status!r}")

        try:
            result = await tm.service.update_task(
                tm.scope, task_id, expected_revision=expected_revision, status=task_status, reason=reason
            )
        except RevisionConflict as exc:
            return _error("revision_conflict", str(exc), expected=exc.expected, current=exc.current)
        except (TaskNotFound, ScopeViolation) as exc:
            return _error("task_not_found", str(exc))
        except PlanValidationError as exc:
            return _error("invalid_transition", str(exc))
        except TaskMemoryError as exc:
            # Reducer refusals (an incomplete plan, an unfinished
            # required step) are answers the model should act on rather
            # than crashes it cannot see.
            return _error("refused", str(exc))

        # A task in a terminal status is no longer a sensible default for
        # later commands, so the selection is cleared.
        if result.state.status.is_terminal:
            await tm.release_selection(task_id)
            if tm.task_id == task_id:
                tm.select(None)

        return {
            "status": "updated",
            "task_status": result.state.status.value,
            "revision": result.state.revision,
        }

    # ── reads: never append, never select ────────────────────────────

    @tool_schema(RecallTaskInput)
    async def recall_task(
        self,
        task_id: Optional[str] = None,
        max_tokens: int = 2500,
        recent_calls_limit: int = 8,
    ) -> dict:
        """Recover a task's actionable state in one bounded read.

        Read-only: appends nothing, loads no payloads, runs no tools, and
        **does not select a task**. Omitting ``task_id`` uses the already
        selected task; when several are open and none is selected you are
        asked to choose from a bounded list — never guessed at.

        Args:
            task_id: Task to recall, or ``None`` for the selected one.
            max_tokens: Budget for the snapshot.
            recent_calls_limit: How many recent tool calls to include.

        Returns:
            A budgeted snapshot with truncation accounting, or a typed
            ``needs_task_selection`` / ``budget_too_small`` answer.
        """
        tm = self._tm()
        # Resolved here rather than left to the reader: the reader can
        # only consult a durable association store, and Delivery A may
        # not have one. Passing the selection we already hold is what
        # makes "omit the id to mean the selected task" work in-process
        # too. Still never a similarity guess — `task_id` stays None when
        # nothing is selected, and the reader answers needs_task_selection.
        resolved = task_id if task_id is not None else tm.task_id
        try:
            result = await tm.reader.recall(
                tm.scope,
                resolved,
                max_tokens=max_tokens,
                recent_calls_limit=recent_calls_limit,
            )
        except ValueError as exc:
            return _error("invalid_budget", str(exc))
        except (TaskNotFound, ScopeViolation) as exc:
            return _error("task_not_found", str(exc))

        if result.status is RecallStatus.NEEDS_TASK_SELECTION:
            return _error(
                "needs_task_selection",
                "no task is selected; call wm_select_task with one of the open tasks",
                open_tasks=result.snapshot.get("open_tasks", []),
            )
        if result.status is RecallStatus.BUDGET_TOO_SMALL:
            return _error(
                "budget_too_small",
                "the required content does not fit the requested budget",
                required_min_tokens=result.required_min_tokens,
            )
        return {
            "status": "recalled",
            "snapshot": result.snapshot,
            "estimated_tokens": result.estimated_tokens,
            "tokens_estimated": result.tokens_estimated,
            "truncation": result.truncation.model_dump(mode="json"),
        }

    @tool_schema(ListTaskEventsInput)
    async def list_task_events(self, task_id: str, after_seq: int = 0, limit: int = 50) -> dict:
        """Page a task's journal in sequence order. Read-only.

        Args:
            task_id: Task to read.
            after_seq: Return events strictly after this sequence.
            limit: Bounded page size.

        Returns:
            The events and the next sequence to resume from.
        """
        tm = self._tm()
        try:
            page = await tm.store.list_events(tm.scope, task_id, after_seq=after_seq, limit=limit)
        except (TaskNotFound, ScopeViolation) as exc:
            return _error("task_not_found", str(exc))

        return {
            "status": "ok",
            "events": [
                {
                    "seq": e.seq,
                    "type": e.event_type.value,
                    "at": e.occurred_at.isoformat(),
                    "actor": e.actor.value,
                    "step_id": e.step_id,
                    "attribution": e.attribution.value,
                }
                for e in page.events
            ],
            "next_seq": page.next_seq,
            "has_more": page.has_more,
        }

    @tool_schema(ListTaskArtifactsInput)
    async def list_task_artifacts(self, task_id: str, limit: int = 50, cursor: Optional[str] = None) -> dict:
        """Page a task's artifact versions. Read-only, metadata only.

        Returns descriptors — never rows, payloads or summaries.

        Args:
            task_id: Task to read.
            limit: Bounded page size.
            cursor: Opaque cursor from a previous page.

        Returns:
            Version descriptors and the next cursor.
        """
        tm = self._tm()
        try:
            page = await tm.artifacts.list(tm.scope, task_id=task_id, limit=limit, cursor=cursor)
        except ScopeViolation as exc:
            return _error("task_not_found", str(exc))
        except TaskMemoryError as exc:
            # A cursor bound to a different scope or query is refused
            # rather than silently restarting the listing from the top.
            return _error("invalid_cursor", str(exc))

        return {
            "status": "ok",
            "artifacts": [
                {
                    "ref": str(d.ref),
                    "alias": d.alias,
                    "kind": d.kind.value,
                    "availability": d.availability.value,
                    "verifiable": d.evidence_verifiable,
                    "invalidated": d.invalidated,
                }
                for d in page.items
            ],
            "next_cursor": page.next_cursor,
        }
