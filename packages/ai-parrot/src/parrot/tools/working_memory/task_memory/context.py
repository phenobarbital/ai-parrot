"""Per-turn task context: declaration registry and invocation receipts (FEAT-538).

This module implements the specification's §2 *Single Observer and Turn
Context* and decision D3. It answers one question — *which task step, if
any, does this tool call belong to?* — and it answers it **truthfully**,
which mostly means refusing to guess.

Why a session object rather than a plain ContextVar
---------------------------------------------------

The obvious design is a ``ContextVar`` holding the declared step ids.
It does not work. ``contextvars`` copies the *context* into a spawned
:class:`asyncio.Task`, so a child that assigns a new value publishes it
to nobody: not to its parent, not to its siblings. A sub-agent that
declares "I am now running step X" inside a child task would be invisible
to the very dispatches that need to see it.

So the runtime owns a :class:`TurnTaskSession` — one mutable object per
turn — and the ContextVar holds a *reference* to it. Mutating the shared
session publishes; rebinding the ContextVar does not. That single
distinction is the whole reason this module exists.

What is frozen and what is not
------------------------------

The session is mutable for the turn's lifetime. Each dispatch takes a
**frozen** :class:`~parrot.tools.working_memory.task_memory.models.
TaskContext` snapshot of it. A declaration made *after* a dispatch never
changes that dispatch's snapshot — attribution is decided at dispatch
time and is never retroactively revised. This is what stops the system
from quietly re-attributing a call once it learns more.

Attribution rules (D3)
----------------------

======================================  ==============================
Declared steps at dispatch              Attribution
======================================  ==============================
zero                                    ``none`` (task-level)
exactly one                             ``declared``
two or more                             ``ambiguous`` (task-level)
explicit plan-to-step mapping           ``plan`` (overrides the above)
plan node with no mapping               ``plan``, task-level
======================================  ==============================

A plan node id is **not** a domain step id. An unmapped plan call keeps
plan provenance and stays task-level rather than being attributed to a
guessed step. And attribution never completes a step: it only records
what the runtime could honestly say about where a call belonged.

Receipt lifetime
----------------

``PlanToolNode._store`` (``bots/flows/plan/node.py:347``) runs *after*
``_call_with_retry`` (``:414``) has already returned, by which time the
dispatcher has reset its per-invocation context. Without help, every
artifact a plan node stores would lose its ``producer_call_id``.
:meth:`TurnTaskSession.retained_producer` is that help: it pins a
completed attempt's call id across the post-dispatch boundary so the
artifact receipt still names the attempt that produced it.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import logging
import threading
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from .models import (
    CallOutcome,
    EvidenceRef,
    InvocationRecord,
    LimitExceeded,
    Limits,
    ScopeViolation,
    TaskContext,
    TaskMemoryError,
    TaskScope,
    new_id,
    utc_now,
)

__all__ = (
    "MAX_DECLARED_STEPS_PER_TURN",
    "TASK_CONTEXT",
    "CURRENT_CALL",
    "RETAINED_PRODUCER",
    "StaleTurnContext",
    "TurnContextEnvelope",
    "TurnTaskSession",
    "async_turn_session",
    "current_call_id",
    "current_session",
    "producer_call_id",
    "run_in_thread",
    "spawn_task",
    "turn_session",
)

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

#: Upper bound on simultaneously declared steps in one turn. Declaring
#: more than a handful is already ``ambiguous`` and therefore useless for
#: attribution; the bound exists so a runaway loop cannot grow the
#: registry without limit. Reuses the domain's per-step reference bound
#: rather than inventing a new limit constant.
MAX_DECLARED_STEPS_PER_TURN: int = Limits.MAX_STEP_DEPENDENCIES

#: The turn's session. Holds a *reference* to a mutable object, so that
#: mutations are shared across child tasks while rebinding is not.
#: Always reset in a ``finally`` — see :func:`turn_session`.
TASK_CONTEXT: contextvars.ContextVar[Optional["TurnTaskSession"]] = contextvars.ContextVar(
    "parrot_task_memory_turn_session", default=None
)

#: The call id of the invocation currently executing in *this* logical
#: context. A nested dispatch reads it as its ``parent_call_id``. Being a
#: ContextVar is correct here: nesting is genuinely per-context, unlike
#: the declaration registry.
CURRENT_CALL: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "parrot_task_memory_current_call", default=None
)

#: A deliberately retained producer call id, surviving past the
#: dispatcher's context reset. Set by
#: :meth:`TurnTaskSession.retained_producer`.
RETAINED_PRODUCER: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "parrot_task_memory_retained_producer", default=None
)


class StaleTurnContext(TaskMemoryError):
    """A serialized turn context no longer matches the live runtime.

    Raised when an envelope returning from a REPL worker names a task,
    worker generation or fencing token that has since moved on. The
    caller must not treat its result as attributable.
    """


class TurnContextEnvelope(BaseModel):
    """The bounded context that may cross a process boundary.

    Only this travels to a REPL worker — never the session, never a
    payload, never anything unbounded. On return, every field is
    revalidated against the live session (:meth:`revalidate`), because a
    worker may have been recycled, the selected task may have changed,
    and a stale generation must not be able to attribute work.

    Attributes:
        scope: Trusted runtime scope at the time of serialization.
        task_id: The selected task, when one was selected.
        turn_id: The conversation turn.
        plan_revision: Plan revision in force.
        call_id: The attempt that crossed the boundary.
        declared_step_ids: Steps declared at serialization time.
        worker_session_id: Identity of the worker process generation.
        worker_generation: Monotonic generation within that session. A
            PID alone is not a generation identity — a recycled worker
            can reuse one.
        fencing_token: Monotonic token proving ownership of the call.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: TaskScope
    task_id: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    turn_id: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    plan_revision: int = Field(default=0, ge=0)
    call_id: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    declared_step_ids: Tuple[str, ...] = ()
    worker_session_id: Optional[str] = Field(default=None, max_length=Limits.MAX_IDENTIFIER)
    worker_generation: int = Field(default=0, ge=0)
    fencing_token: int = Field(default=0, ge=0)

    def revalidate(
        self,
        session: "TurnTaskSession",
        *,
        worker_session_id: Optional[str] = None,
        worker_generation: Optional[int] = None,
        fencing_token: Optional[int] = None,
    ) -> None:
        """Check this envelope against the live session on return.

        Args:
            session: The session the work belongs to.
            worker_session_id: The worker generation identity observed on
                return, when the caller can supply one.
            worker_generation: The generation counter observed on return.
            fencing_token: The ownership token observed on return.

        Raises:
            ScopeViolation: If the scope no longer matches. This is a
                hard boundary: a mismatched scope is a cross-user read.
            StaleTurnContext: If the selected task, worker generation or
                fencing token moved on while the work was out of process.
        """
        if not session.scope.matches(self.scope):
            raise ScopeViolation("returned turn context belongs to a different scope")
        if self.task_id != session.task_id:
            raise StaleTurnContext(
                f"selected task changed while work was out of process: "
                f"envelope={self.task_id!r}, current={session.task_id!r}"
            )
        if worker_session_id is not None and worker_session_id != self.worker_session_id:
            raise StaleTurnContext(
                f"worker generation identity changed: envelope={self.worker_session_id!r}, "
                f"observed={worker_session_id!r}"
            )
        if worker_generation is not None and worker_generation != self.worker_generation:
            raise StaleTurnContext(
                f"worker generation changed: envelope={self.worker_generation}, observed={worker_generation}"
            )
        if fencing_token is not None and fencing_token != self.fencing_token:
            raise StaleTurnContext(f"fencing token changed: envelope={self.fencing_token}, observed={fencing_token}")


class TurnTaskSession:
    """One turn's shared, mutable task context.

    Held by reference in :data:`TASK_CONTEXT` so that every child task
    and thread of the turn sees the *same* object. Mutation is what
    publishes.

    The declaration registry is guarded by a :class:`threading.RLock`
    rather than an :class:`asyncio.Lock`, deliberately: the registry is
    also mutated from thread work (``asyncio.to_thread`` and
    :func:`run_in_thread`), which an asyncio lock cannot protect. Every
    critical section is a few dict operations with no I/O and no await,
    so the lock is never held across a suspension point and cannot stall
    the event loop.

    Attributes:
        scope: Trusted runtime scope for the whole turn.
        turn_id: The conversation turn's identity.
    """

    __slots__ = (
        "scope",
        "turn_id",
        "owner",
        "_task_id",
        "_plan_revision",
        "_declared",
        "_lock",
        "_records",
        "_by_call_id",
        "_open_calls",
        "_quiet",
    )

    def __init__(
        self,
        scope: TaskScope,
        *,
        turn_id: Optional[str] = None,
        task_id: Optional[str] = None,
        plan_revision: int = 0,
        owner: Optional[str] = None,
    ) -> None:
        """Initialize a turn session.

        Args:
            scope: Trusted runtime scope. Never taken from a tool
                argument.
            turn_id: The conversation turn's identity; generated when
                omitted.
            task_id: The initially selected task, if any.
            plan_revision: Plan revision in force at the turn's start.
            owner: Opaque identity of the worker running this turn, used
                to claim and heartbeat per-call ownership. Generated when
                omitted, which is what makes two processes — or two turns
                in one process — distinguishable to a fencing check.
        """
        self.scope = scope
        self.turn_id = turn_id or new_id()
        self.owner = owner or new_id()
        self._task_id = task_id
        self._plan_revision = plan_revision
        self._declared: Dict[str, int] = {}
        self._lock = threading.RLock()
        self._records: List[InvocationRecord] = []
        self._by_call_id: Dict[str, InvocationRecord] = {}
        self._open_calls: Dict[str, InvocationRecord] = {}
        self._quiet: Optional[asyncio.Event] = None

    # ── selection and plan revision ──────────────────────────────────

    @property
    def task_id(self) -> Optional[str]:
        """The currently selected task, or ``None``."""
        with self._lock:
            return self._task_id

    def select_task(self, task_id: Optional[str]) -> None:
        """Select (or clear) the task this turn's work belongs to.

        Args:
            task_id: The task to select, or ``None`` to clear.
        """
        with self._lock:
            self._task_id = task_id

    @property
    def plan_revision(self) -> int:
        """The plan revision in force for new snapshots."""
        with self._lock:
            return self._plan_revision

    def set_plan_revision(self, revision: int) -> None:
        """Record a new plan revision for subsequent snapshots.

        Args:
            revision: The new plan revision.

        Raises:
            ValueError: If ``revision`` is negative.
        """
        if revision < 0:
            raise ValueError(f"plan_revision must be >= 0, got {revision}")
        with self._lock:
            self._plan_revision = revision

    # ── declaration registry ─────────────────────────────────────────

    @property
    def declared_step_ids(self) -> Tuple[str, ...]:
        """Currently declared step ids, in declaration order."""
        with self._lock:
            return tuple(sorted(self._declared, key=self._declared.__getitem__))

    def declare(self, step_id: str) -> None:
        """Declare that a step is running for this turn.

        Called after a *successful* running-step update, so the shared
        session is what publishes the fact — including from inside a
        child task, where a ContextVar assignment would reach nobody.

        Re-declaring an already-declared step is a no-op and keeps its
        original position, so a retry cannot make attribution look
        ambiguous.

        Args:
            step_id: The step now running.

        Raises:
            LimitExceeded: If the turn already declares
                :data:`MAX_DECLARED_STEPS_PER_TURN` steps.
            ValueError: If ``step_id`` is empty or over-long.
        """
        if not step_id or len(step_id) > Limits.MAX_IDENTIFIER:
            raise ValueError(f"invalid step_id: {step_id!r}")
        with self._lock:
            if step_id in self._declared:
                return
            if len(self._declared) >= MAX_DECLARED_STEPS_PER_TURN:
                raise LimitExceeded("declared steps per turn", MAX_DECLARED_STEPS_PER_TURN, len(self._declared) + 1)
            self._declared[step_id] = len(self._declared)

    def undeclare(self, step_id: str) -> bool:
        """Withdraw a declaration.

        Args:
            step_id: The step to withdraw.

        Returns:
            ``True`` when the step had been declared.
        """
        with self._lock:
            return self._declared.pop(step_id, None) is not None

    @contextmanager
    def declaration(self, step_id: str) -> Iterator["TurnTaskSession"]:
        """Declare ``step_id`` for the duration of the block.

        The declaration is withdrawn in a ``finally``, so an exception or
        a cancellation inside the block cannot leave the turn looking
        ambiguous for every later dispatch.

        Args:
            step_id: The step to declare.

        Yields:
            This session.
        """
        self.declare(step_id)
        try:
            yield self
        finally:
            self.undeclare(step_id)

    # ── snapshots ────────────────────────────────────────────────────

    def snapshot(
        self,
        *,
        parent_call_id: Optional[str] = None,
        plan_run_id: Optional[str] = None,
        plan_node_id: Optional[str] = None,
        plan_item_index: Optional[int] = None,
        plan_attempt: Optional[int] = None,
        mapped_step_id: Optional[str] = None,
    ) -> TaskContext:
        """Freeze the session's current state into a dispatch snapshot.

        Everything is read under one lock acquisition so the snapshot is
        internally consistent even while other tasks are declaring.

        Args:
            parent_call_id: Parent aggregate call, when nested. Defaults
                to the call currently executing in this context.
            plan_run_id: Explicit plan-run correlation.
            plan_node_id: Explicit plan-node correlation.
            plan_item_index: Fan-out index within a plan node.
            plan_attempt: Attempt number within the node's retry policy.
            mapped_step_id: Step id resolved by an explicit
                plan-to-step mapping. Supplying it is the *only* way a
                plan call gets attributed to a specific step.

        Returns:
            An immutable :class:`TaskContext`.
        """
        with self._lock:
            declared = tuple(sorted(self._declared, key=self._declared.__getitem__))
            task_id = self._task_id
            plan_revision = self._plan_revision
        return TaskContext(
            scope=self.scope,
            task_id=task_id,
            plan_revision=plan_revision,
            turn_id=self.turn_id,
            declared_step_ids=declared,
            parent_call_id=parent_call_id if parent_call_id is not None else CURRENT_CALL.get(),
            plan_run_id=plan_run_id,
            plan_node_id=plan_node_id,
            plan_item_index=plan_item_index,
            plan_attempt=plan_attempt,
            mapped_step_id=mapped_step_id,
        )

    def envelope(
        self,
        *,
        call_id: Optional[str] = None,
        worker_session_id: Optional[str] = None,
        worker_generation: int = 0,
        fencing_token: int = 0,
    ) -> TurnContextEnvelope:
        """Serialize the bounded context that may cross a process boundary.

        Args:
            call_id: The attempt crossing the boundary. Defaults to the
                call currently executing in this context.
            worker_session_id: Identity of the worker process generation.
            worker_generation: Generation counter within that session.
            fencing_token: Ownership token for the call.

        Returns:
            The envelope. Nothing unbounded and no payload travels in it.
        """
        with self._lock:
            declared = tuple(sorted(self._declared, key=self._declared.__getitem__))
            task_id = self._task_id
            plan_revision = self._plan_revision
        return TurnContextEnvelope(
            scope=self.scope,
            task_id=task_id,
            turn_id=self.turn_id,
            plan_revision=plan_revision,
            call_id=call_id if call_id is not None else CURRENT_CALL.get(),
            declared_step_ids=declared,
            worker_session_id=worker_session_id,
            worker_generation=worker_generation,
            fencing_token=fencing_token,
        )

    # ── invocation receipts ──────────────────────────────────────────

    @property
    def records(self) -> Tuple[InvocationRecord, ...]:
        """Every attempt captured this turn, in start order.

        This is the canonical capture the enabled path hands to both
        journal derivation and ``ConversationTurn.tool_invocations``. It
        is produced **once**; the legacy ``AIMessage.tool_calls``
        conversion must be replaced by it, not concatenated with it.
        """
        with self._lock:
            return tuple(self._records)

    @property
    def open_call_ids(self) -> Tuple[str, ...]:
        """Call ids of attempts that have started but not terminated."""
        with self._lock:
            return tuple(self._open_calls)

    def receipt(self, call_id: str) -> Optional[InvocationRecord]:
        """Look up one attempt's receipt by call id.

        Args:
            call_id: The attempt's identity.

        Returns:
            The record, or ``None`` when this turn has no such attempt.
        """
        with self._lock:
            return self._by_call_id.get(call_id)

    def begin_invocation(
        self,
        tool_name: str,
        *,
        attempt: int = 1,
        parent_call_id: Optional[str] = None,
        plan_run_id: Optional[str] = None,
        plan_node_id: Optional[str] = None,
        plan_item_index: Optional[int] = None,
        plan_attempt: Optional[int] = None,
        mapped_step_id: Optional[str] = None,
    ) -> InvocationRecord:
        """Open a receipt for one physical dispatch attempt.

        The frozen snapshot is taken here, at dispatch time. Declarations
        made later do not change it.

        Args:
            tool_name: The tool about to be dispatched.
            attempt: 1-based attempt number for this physical call.
            parent_call_id: Parent aggregate call; defaults to the call
                currently executing in this context.
            plan_run_id: Explicit plan-run correlation.
            plan_node_id: Explicit plan-node correlation.
            plan_item_index: Fan-out index within a plan node.
            plan_attempt: Attempt number within the node's retry policy.
            mapped_step_id: Step resolved by an explicit plan-to-step
                mapping.

        Returns:
            The open :class:`InvocationRecord`.
        """
        context = self.snapshot(
            parent_call_id=parent_call_id,
            plan_run_id=plan_run_id,
            plan_node_id=plan_node_id,
            plan_item_index=plan_item_index,
            plan_attempt=plan_attempt,
            mapped_step_id=mapped_step_id,
        )
        record = InvocationRecord(
            attempt=attempt,
            parent_call_id=context.parent_call_id,
            tool_name=tool_name,
            context=context,
            started_at=utc_now(),
        )
        with self._lock:
            self._records.append(record)
            self._by_call_id[record.call_id] = record
            self._open_calls[record.call_id] = record
        return record

    def complete_invocation(
        self,
        record: InvocationRecord,
        *,
        outcome: CallOutcome,
        executed: bool,
        error: Optional[str] = None,
        elapsed_ms: Optional[int] = None,
        invocation: Any = None,
        artifact_receipts: Sequence[EvidenceRef] = (),
        degraded: bool = False,
        finished_at: Optional[datetime] = None,
    ) -> InvocationRecord:
        """Close a receipt with its typed terminal outcome.

        Args:
            record: The open receipt.
            outcome: Typed outcome of the attempt.
            executed: Whether a tool body actually ran. ``False`` for the
                dispatcher's early returns — an unknown tool or a guard
                denial is an unsuccessful *dispatch*, not a failed tool.
            error: Condensed, redacted error text.
            elapsed_ms: Wall-clock duration.
            invocation: The canonical compaction ``ToolInvocation``.
            artifact_receipts: Artifact versions this attempt produced.
            degraded: Whether tracking for this attempt is degraded.
            finished_at: Termination time; defaults to now.

        Returns:
            The same record, now closed.
        """
        record.outcome = outcome
        record.executed = executed
        record.error = error
        record.elapsed_ms = elapsed_ms
        record.invocation = invocation
        record.artifact_receipts = tuple(artifact_receipts)
        record.degraded = degraded
        record.finished_at = finished_at or utc_now()
        with self._lock:
            self._open_calls.pop(record.call_id, None)
            quiet = self._quiet
            if quiet is not None and not self._open_calls:
                quiet.set()
        return record

    def add_artifact_receipt(self, call_id: str, ref: EvidenceRef) -> bool:
        """Attach an artifact version to an attempt, even after it closed.

        This is what keeps ``producer_call_id`` intact for a plan node,
        whose ``_store`` runs after dispatch has already returned.

        Args:
            call_id: The producing attempt.
            ref: The artifact version it produced.

        Returns:
            ``True`` when the attempt belongs to this turn.
        """
        with self._lock:
            record = self._by_call_id.get(call_id)
            if record is None:
                return False
            if ref not in record.artifact_receipts:
                record.artifact_receipts = record.artifact_receipts + (ref,)
            return True

    @contextmanager
    def invocation(
        self,
        tool_name: str,
        *,
        attempt: int = 1,
        parent_call_id: Optional[str] = None,
        plan_run_id: Optional[str] = None,
        plan_node_id: Optional[str] = None,
        plan_item_index: Optional[int] = None,
        plan_attempt: Optional[int] = None,
        mapped_step_id: Optional[str] = None,
    ) -> Iterator[InvocationRecord]:
        """Open a receipt, publish it as the current call, and always close it.

        Wrap the dispatch itself::

            with session.invocation("wm_store") as receipt:
                result = await manager.execute_tool(...)
                session.complete_invocation(receipt, outcome=..., executed=True)

        If the block raises — including :class:`asyncio.CancelledError`
        from a cancelled stream — the receipt is closed with a truthful
        outcome and :data:`CURRENT_CALL` is reset regardless. Cancellation
        recording is bounded (a status flip, no I/O) and the cancellation
        is then re-raised unchanged.

        Args:
            tool_name: The tool about to be dispatched.
            attempt: 1-based attempt number.
            parent_call_id: Parent aggregate call.
            plan_run_id: Explicit plan-run correlation.
            plan_node_id: Explicit plan-node correlation.
            plan_item_index: Fan-out index within a plan node.
            plan_attempt: Attempt number within the node's retry policy.
            mapped_step_id: Step resolved by an explicit mapping.

        Yields:
            The open :class:`InvocationRecord`.
        """
        record = self.begin_invocation(
            tool_name,
            attempt=attempt,
            parent_call_id=parent_call_id,
            plan_run_id=plan_run_id,
            plan_node_id=plan_node_id,
            plan_item_index=plan_item_index,
            plan_attempt=plan_attempt,
            mapped_step_id=mapped_step_id,
        )
        token = CURRENT_CALL.set(record.call_id)
        try:
            yield record
        except asyncio.CancelledError:
            # Bounded, no I/O — then propagate the cancellation unchanged.
            if record.outcome is None:
                self.complete_invocation(record, outcome=CallOutcome.CANCELLED, executed=True)
            raise
        except BaseException:
            if record.outcome is None:
                self.complete_invocation(record, outcome=CallOutcome.UNKNOWN, executed=True)
            raise
        finally:
            CURRENT_CALL.reset(token)
            with self._lock:
                if record.call_id in self._open_calls and record.outcome is not None:
                    self._open_calls.pop(record.call_id, None)

    @contextmanager
    def retained_producer(self, call_id: str) -> Iterator[str]:
        """Keep ``call_id`` attributable past the dispatcher's context reset.

        ``PlanToolNode`` wraps its post-dispatch ``_store`` in this, so
        the artifact it registers still records the attempt that produced
        it. Without it, :data:`CURRENT_CALL` has already been reset by
        the time ``_store`` runs and the provenance is simply lost.

        Args:
            call_id: The producing attempt.

        Yields:
            The retained call id.
        """
        token = RETAINED_PRODUCER.set(call_id)
        try:
            yield call_id
        finally:
            RETAINED_PRODUCER.reset(token)

    # ── barriers ─────────────────────────────────────────────────────

    async def barrier(self) -> None:
        """Wait until every in-flight attempt in this turn has terminated.

        The specification requires *explicit* completion barriers before
        concurrent control mutations and dependent work, precisely so the
        runtime never has to retroactively guess attribution. This is
        that barrier: await it before declaring a step whose attribution
        must not be confused with work already in flight.
        """
        with self._lock:
            if not self._open_calls:
                return
            if self._quiet is None:
                self._quiet = asyncio.Event()
            quiet = self._quiet
            quiet.clear()
        await quiet.wait()
        with self._lock:
            if not self._open_calls:
                self._quiet = None

    def __repr__(self) -> str:
        """Return a debug representation (never includes payloads)."""
        return (
            f"TurnTaskSession(turn_id={self.turn_id!r}, task_id={self.task_id!r}, "
            f"declared={len(self._declared)}, records={len(self._records)})"
        )


# ─────────────────────────────────────────────────────────────
# Lifecycle
# ─────────────────────────────────────────────────────────────


@contextmanager
def turn_session(
    scope: TaskScope,
    *,
    turn_id: Optional[str] = None,
    task_id: Optional[str] = None,
    plan_revision: int = 0,
    owner: Optional[str] = None,
    session: Optional[TurnTaskSession] = None,
) -> Iterator[TurnTaskSession]:
    """Bind a turn session to :data:`TASK_CONTEXT` for the block.

    The token is reset in a ``finally``, so scope never leaks past the
    turn — not on an exception, and not when a streaming generator is
    cancelled and finalized.

    Works in synchronous and asynchronous code alike; ``with`` around an
    ``await`` is fine, because binding a ContextVar involves no
    suspension.

    Args:
        scope: Trusted runtime scope for the turn.
        turn_id: The conversation turn's identity.
        task_id: Initially selected task, if any.
        plan_revision: Plan revision in force at the turn's start.
        owner: Opaque worker identity for per-call ownership.
        session: An existing session to rebind instead of creating one.

    Yields:
        The bound :class:`TurnTaskSession`.
    """
    active = session or TurnTaskSession(
        scope, turn_id=turn_id, task_id=task_id, plan_revision=plan_revision, owner=owner
    )
    token = TASK_CONTEXT.set(active)
    try:
        yield active
    finally:
        TASK_CONTEXT.reset(token)


@asynccontextmanager
async def async_turn_session(
    scope: TaskScope,
    *,
    turn_id: Optional[str] = None,
    task_id: Optional[str] = None,
    plan_revision: int = 0,
    owner: Optional[str] = None,
    session: Optional[TurnTaskSession] = None,
):
    """``async with`` form of :func:`turn_session`.

    Args:
        scope: Trusted runtime scope for the turn.
        turn_id: The conversation turn's identity.
        task_id: Initially selected task, if any.
        plan_revision: Plan revision in force at the turn's start.
        owner: Opaque worker identity for per-call ownership.
        session: An existing session to rebind instead of creating one.

    Yields:
        The bound :class:`TurnTaskSession`.
    """
    with turn_session(
        scope, turn_id=turn_id, task_id=task_id, plan_revision=plan_revision, owner=owner, session=session
    ) as active:
        yield active


def current_session() -> Optional[TurnTaskSession]:
    """Return the turn session bound to this context, if any.

    Returns:
        The session, or ``None`` when task memory is disabled or the
        turn has ended.
    """
    return TASK_CONTEXT.get()


def current_call_id() -> Optional[str]:
    """Return the call id currently executing in this context.

    Returns:
        The call id, or ``None`` outside a dispatch.
    """
    return CURRENT_CALL.get()


def producer_call_id() -> Optional[str]:
    """Return the call id an artifact registered *now* should be attributed to.

    An explicitly retained producer wins over the ambient current call:
    that is the whole point of :meth:`TurnTaskSession.retained_producer`,
    which exists because a plan node's ``_store`` runs after dispatch has
    already reset the ambient value.

    Returns:
        The producing call id, or ``None`` when there is nothing to
        attribute to. ``None`` is a truthful answer — it is never
        replaced with a guess.
    """
    retained = RETAINED_PRODUCER.get()
    return retained if retained is not None else CURRENT_CALL.get()


# ─────────────────────────────────────────────────────────────
# Propagation to tasks and threads
# ─────────────────────────────────────────────────────────────


def spawn_task(coro: Any, *, name: Optional[str] = None) -> "asyncio.Task[Any]":
    """Spawn a child task that shares this turn's session.

    :func:`asyncio.create_task` already copies the context, so the child
    sees the *same* session object and its mutations are published back
    to the parent and to siblings. This wrapper exists to make that
    guarantee explicit at the call site rather than incidental.

    Args:
        coro: The coroutine to run.
        name: Optional task name.

    Returns:
        The spawned task.
    """
    return asyncio.create_task(coro, name=name)


async def run_in_thread(fn: Callable[..., _T], /, *args: Any, **kwargs: Any) -> _T:
    """Run ``fn`` in a worker thread with this turn's context copied in.

    :func:`asyncio.to_thread` propagates context, but
    ``ThreadPoolExecutor.submit`` and a bare :class:`threading.Thread` do
    not — and a thread that cannot see the session cannot declare or
    record anything. This helper copies the context explicitly so
    off-loop work is never silently unattributed.

    Args:
        fn: The callable to run.
        *args: Positional arguments for ``fn``.
        **kwargs: Keyword arguments for ``fn``.

    Returns:
        Whatever ``fn`` returns.
    """
    context = contextvars.copy_context()
    call = functools.partial(fn, *args, **kwargs)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: context.run(call))
