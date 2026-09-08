"""The single canonical invocation observer (FEAT-538, decision D5).

One observer wraps the manager's dispatch, and it is the only place tool
activity is captured. Everything downstream — the journal, and
``ConversationTurn.tool_invocations`` — derives from the *same*
:class:`InvocationRecord`, so the two can never disagree about what
happened.

Ordering is the whole design, and it is not negotiable:

``tool_started`` is persisted **after** authorization and **immediately
before** an actual execution attempt.
    Persisting it earlier would record starts for calls a guard was about
    to refuse. Persisting it later would let an external effect happen
    with no durable record that it might have.

The terminal result is persisted **before** success is reported.
    If the effect ran but the terminal write failed, the caller is told
    the outcome is *unknown* — never that it succeeded. Reporting success
    on an unpersisted terminal is what makes a crash indistinguishable
    from a clean run, and it is what invites an automatic retry of an
    effect that may already have happened.

Failure modes, made explicit (D8):

- **Durable mode.** If ``tool_started`` cannot be persisted, the call does
  not run: :class:`TaskMemoryUnavailable` is raised *before* dispatch.
  This is fail-closed on purpose — an untracked external effect is worse
  than a refused one.
- **Best-effort mode.** Only with an explicit opt-in. The call proceeds,
  but the result carries ``tracking_degraded`` so nobody mistakes it for
  tracked work.

Denials and unknown tools are classified as unsuccessful *dispatch*
outcomes with ``executed=False``. They never get a fictitious
``tool_started``, because no tool body ran.

Cancellation is recorded on a shielded, bounded path and then re-raised.
Swallowing a ``CancelledError`` to finish bookkeeping would turn a
cancelled call into a completed one.

Read-only commands — recall and the listing tools — are exempt: they
append nothing, so repeated reads cannot change a task's sequence or fill
its journal (AC10).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Optional, Sequence, Set

from .adapters import DispatchOutcome, classify, classify_exception
from .context import TurnTaskSession
from .models import (
    Actor,
    CallOutcome,
    DegradedPayload,
    EventType,
    EvidenceRef,
    InvocationRecord,
    JournalEvent,
    TaskMemoryUnavailable,
    ToolCallPayload,
    new_id,
    utc_now,
)

__all__ = (
    "READ_ONLY_TOOLS",
    "ObserverMode",
    "ObservedCall",
    "InvocationObserver",
)

#: Tools that never mutate a task's journal. Recall and the listing
#: commands must be free to run repeatedly: if observing them appended
#: events, reading a task would change it, and recall would stop being
#: deterministic for a captured sequence.
READ_ONLY_TOOLS: Set[str] = {
    "wm_recall_task",
    "wm_list_task_events",
    "wm_list_task_artifacts",
    "wm_get_result",
    "wm_list_stored",
}


class ObserverMode:
    """How the observer behaves when the journal is unavailable."""

    #: Refuse to execute rather than run an untracked effect (D8 default).
    DURABLE = "durable"
    #: Explicit opt-in: run anyway, and report ``tracking_degraded``.
    BEST_EFFORT = "best_effort"


class ObservedCall:
    """One in-flight observation.

    Returned by :meth:`InvocationObserver.begin` and handed back to
    :meth:`InvocationObserver.finish`. Holding the record here rather than
    in a ContextVar is what lets a *nested* plan call keep its own
    identity while its parent is still open.

    Attributes:
        record: The canonical invocation record.
        started_at: Monotonic start, for the elapsed measurement.
        degraded: Whether the start could not be persisted.
        journalled: Whether a ``tool_started`` actually reached the
            journal. A terminal event is only meaningful if it did.
    """

    __slots__ = ("record", "started_at", "degraded", "journalled")

    def __init__(self, record: InvocationRecord, *, degraded: bool = False, journalled: bool = True) -> None:
        """Initialize an observation.

        Args:
            record: The canonical record.
            degraded: Whether tracking is degraded for this call.
            journalled: Whether the start was persisted.
        """
        self.record = record
        self.started_at = time.monotonic()
        self.degraded = degraded
        self.journalled = journalled

    @property
    def call_id(self) -> str:
        """This physical attempt's identity."""
        return self.record.call_id

    def elapsed_ms(self) -> int:
        """Return the elapsed wall time in milliseconds."""
        return int((time.monotonic() - self.started_at) * 1000)


#: What the observer needs from a journal. Deliberately narrower than the
#: whole store: the observer appends and nothing else.
AppendEvents = Callable[[str, Sequence[JournalEvent]], Awaitable[Any]]


class InvocationObserver:
    """Captures every dispatch once, and journals it in the right order.

    Args:
        session: The per-turn session that owns the declaration registry
            and mints call ids.
        append: Callable that appends events to a task's journal.
            ``None`` disables journalling entirely — the collector still
            captures records for the conversation turn, which is what the
            disabled-but-observed configuration needs.
        mode: :data:`ObserverMode.DURABLE` (fail closed) or
            :data:`ObserverMode.BEST_EFFORT` (opt-in, reports degraded).
        read_only_tools: Tool names that must never append events.
    """

    def __init__(
        self,
        session: TurnTaskSession,
        *,
        append: Optional[AppendEvents] = None,
        mode: str = ObserverMode.DURABLE,
        read_only_tools: Optional[Set[str]] = None,
    ) -> None:
        """Initialize the observer."""
        self._session = session
        self._append = append
        self._mode = mode
        self._read_only = set(read_only_tools if read_only_tools is not None else READ_ONLY_TOOLS)

    # ── lifecycle ────────────────────────────────────────────────────

    @property
    def records(self) -> Sequence[InvocationRecord]:
        """Every record captured this turn, in dispatch order.

        This is the single source for ``ConversationTurn.tool_invocations``:
        the enabled path **replaces** the legacy ``AIMessage.tool_calls``
        conversion rather than appending to it, so an observed turn cannot
        end up with each call listed twice.
        """
        return self._session.records

    def is_read_only(self, tool_name: str) -> bool:
        """Whether a tool is exempt from journalling.

        Args:
            tool_name: The tool being dispatched.

        Returns:
            ``True`` when observing it must append nothing.
        """
        return tool_name in self._read_only

    async def begin(
        self,
        tool_name: str,
        *,
        attempt: int = 1,
        parent_call_id: Optional[str] = None,
        **correlation: Any,
    ) -> ObservedCall:
        """Open an observation, persisting ``tool_started`` first.

        Call this **after** every guard has passed and **immediately
        before** the actual execution attempt.

        Args:
            tool_name: The tool about to run.
            attempt: 1-based physical attempt number.
            parent_call_id: Parent aggregate, for a nested plan call.
            **correlation: Plan run/node/item/attempt and mapped-step
                correlation, forwarded to the session.

        Returns:
            The open observation.

        Raises:
            TaskMemoryUnavailable: In durable mode, when the start cannot
                be persisted. Raised **before** the call runs, so no
                untracked external effect occurs.
        """
        record = self._session.begin_invocation(
            tool_name, attempt=attempt, parent_call_id=parent_call_id, **correlation
        )

        if not self._should_journal(tool_name):
            return ObservedCall(record, journalled=False)

        payload = ToolCallPayload(
            call_id=record.call_id,
            tool_name=tool_name,
            attempt=attempt,
            executed=True,
            counted=False,
        )
        try:
            await self._journal(record, EventType.TOOL_STARTED, payload)
        except Exception as exc:  # noqa: BLE001 — the failure mode IS the feature
            if self._mode == ObserverMode.DURABLE:
                # Fail closed. An untracked external effect is worse than
                # a refused one, so this raises BEFORE dispatch.
                raise TaskMemoryUnavailable(
                    f"cannot persist tool_started for {tool_name!r}; refusing to run it untracked"
                ) from exc
            await self._degrade("journal", f"tool_started for {tool_name!r} was not persisted: {exc}")
            return ObservedCall(record, degraded=True, journalled=False)

        return ObservedCall(record, journalled=True)

    async def finish(
        self,
        call: ObservedCall,
        *,
        value: Any = None,
        exception: Optional[BaseException] = None,
        invocation: Any = None,
        artifact_receipts: Sequence[EvidenceRef] = (),
    ) -> DispatchOutcome:
        """Close an observation, persisting the terminal event first.

        The terminal event is written **before** the caller is told the
        call succeeded. If the effect ran but this write fails, the
        outcome is downgraded to ``unknown`` and marked degraded — never
        reported as a success, and never as safe to retry.

        Args:
            call: The open observation.
            value: The dispatch's return value, when it returned.
            exception: The exception it raised, when it raised.
            invocation: The canonical compaction ``ToolInvocation``.
            artifact_receipts: Artifact versions this attempt produced.

        Returns:
            The classified :class:`DispatchOutcome`, downgraded to
            ``unknown`` when its terminal event could not be persisted.
        """
        outcome = classify_exception(exception) if exception is not None else classify(value=value)
        elapsed = call.elapsed_ms()

        record = self._session.complete_invocation(
            call.record,
            outcome=outcome.outcome,
            executed=outcome.executed,
            error=outcome.error,
            elapsed_ms=elapsed,
            invocation=invocation,
            artifact_receipts=artifact_receipts,
            degraded=call.degraded,
        )

        if not call.journalled:
            return outcome

        event_type = record.terminal_event_type or EventType.TOOL_OUTCOME_UNKNOWN
        payload = ToolCallPayload(
            call_id=record.call_id,
            tool_name=record.tool_name,
            attempt=record.attempt,
            executed=outcome.executed,
            outcome=outcome.outcome,
            error=outcome.error,
            elapsed_ms=elapsed,
            artifact_refs=tuple(artifact_receipts),
            # Exactly one terminal event per PHYSICAL attempt counts it.
            # A call that never executed is not an attempt at all, and a
            # parent AGGREGATE is not one either — see `_is_aggregate`.
            counted=outcome.executed and not self._is_aggregate(record.call_id),
        )

        try:
            await self._journal(record, event_type, payload)
        except Exception as exc:  # noqa: BLE001 — the failure mode IS the feature
            # The effect may already have happened. Saying "success" here
            # would make a crash indistinguishable from a clean run and
            # would invite retrying an effect that already occurred.
            await self._degrade("journal", f"terminal event for {record.tool_name!r} was not persisted: {exc}")
            return DispatchOutcome(
                outcome=CallOutcome.UNKNOWN,
                executed=outcome.executed,
                error=(
                    "the tool ran but its outcome could not be persisted; "
                    "treat this as UNKNOWN and do not retry automatically"
                ),
                status=outcome.status,
                partial=outcome.partial,
                source=outcome.source,
            )
        return outcome

    async def cancelled(self, call: ObservedCall) -> None:
        """Record a cancellation, shielded and bounded, then let it propagate.

        The caller re-raises. Swallowing a ``CancelledError`` to finish
        bookkeeping would turn a cancelled call into a completed one, so
        the recording is shielded and bounded rather than merely awaited.

        Args:
            call: The open observation.
        """
        record = self._session.complete_invocation(
            call.record,
            outcome=CallOutcome.CANCELLED,
            executed=True,
            elapsed_ms=call.elapsed_ms(),
            degraded=call.degraded,
        )
        if not call.journalled:
            return

        payload = ToolCallPayload(
            call_id=record.call_id,
            tool_name=record.tool_name,
            attempt=record.attempt,
            executed=True,
            outcome=CallOutcome.CANCELLED,
            elapsed_ms=call.elapsed_ms(),
            counted=not self._is_aggregate(record.call_id),
        )
        try:
            await asyncio.shield(
                asyncio.wait_for(self._journal(record, EventType.TOOL_CANCELLED, payload), timeout=5.0)
            )
        except Exception:  # noqa: BLE001 — cancellation must still propagate
            # A cancellation we could not record is still a cancellation.
            # Never let bookkeeping suppress it.
            pass

    async def not_executed(
        self,
        tool_name: str,
        *,
        value: Any = None,
        exception: Optional[BaseException] = None,
        attempt: int = 1,
    ) -> DispatchOutcome:
        """Record a dispatch that never reached a tool body.

        Unknown tools, guardrail and grant denials, and authorization
        requirements all land here. They get **no** ``tool_started``: a
        fictitious start would claim an execution that never occurred and
        would make the journal's attempt counts wrong.

        Args:
            tool_name: The tool that was refused.
            value: The early-return envelope, when there was one.
            exception: The exception, when there was one.
            attempt: The attempt number.

        Returns:
            The classified outcome, always with ``executed=False``.
        """
        outcome = classify_exception(exception, executed=False) if exception is not None else classify(value=value)
        record = self._session.begin_invocation(tool_name, attempt=attempt)
        self._session.complete_invocation(
            record,
            outcome=outcome.outcome,
            executed=False,
            error=outcome.error,
            elapsed_ms=0,
        )

        if self._should_journal(tool_name):
            payload = ToolCallPayload(
                call_id=record.call_id,
                tool_name=tool_name,
                attempt=attempt,
                executed=False,
                outcome=outcome.outcome,
                error=outcome.error,
                counted=False,  # never executed, so never a physical attempt
            )
            try:
                await self._journal(record, EventType.TOOL_FAILED, payload)
            except Exception:  # noqa: BLE001 — a denial is not worth failing over
                pass

        return DispatchOutcome(
            outcome=outcome.outcome,
            executed=False,
            error=outcome.error,
            status=outcome.status,
            partial=outcome.partial,
            source=outcome.source,
        )

    # ── internals ────────────────────────────────────────────────────

    def _is_aggregate(self, call_id: str) -> bool:
        """Whether this call is a parent aggregate rather than a physical attempt.

        A call is an aggregate when other calls this turn name it as
        their parent — a plan node, say, whose children did the actual
        work. Counting it would count each child's execution twice.

        Note that ``parent_call_id is None`` is NOT the test: an ordinary
        top-level tool call also has no parent, and it *is* a physical
        attempt. What distinguishes an aggregate is having children.

        Evaluated at terminal time, which is sound because an aggregate
        necessarily terminates *after* the children it aggregates — it is
        waiting on them. A parent that somehow finished first would have
        nothing to aggregate yet, and counting it as a physical attempt
        would then be the correct answer anyway.

        Args:
            call_id: The call to classify.

        Returns:
            ``True`` when at least one other record names it as parent.
        """
        return any(r.parent_call_id == call_id for r in self._session.records)

    def _should_journal(self, tool_name: str) -> bool:
        """Whether this dispatch should append events.

        Args:
            tool_name: The tool being dispatched.

        Returns:
            ``True`` when a journal is configured, a task is selected and
            the tool is not read-only.
        """
        return self._append is not None and self._session.task_id is not None and not self.is_read_only(tool_name)

    async def _journal(self, record: InvocationRecord, event_type: EventType, payload: Any) -> None:
        """Append one event derived from a record.

        Args:
            record: The canonical record supplying correlation.
            event_type: The event type.
            payload: Its typed payload.

        Raises:
            Exception: Whatever the append raised. Callers decide the
                failure policy; this method never swallows.
        """
        assert self._append is not None
        context = record.context
        event = JournalEvent(
            event_id=new_id(),
            task_id=context.task_id or "",
            occurred_at=utc_now(),
            event_type=event_type,
            actor=Actor.RUNTIME,
            turn_id=context.turn_id,
            plan_revision=context.plan_revision,
            step_id=context.attributed_step_id,
            call_id=record.call_id,
            parent_call_id=record.parent_call_id,
            attribution=context.attribution,
            payload=payload,
        )
        await self._append(context.task_id or "", [event])

    async def _degrade(self, component: str, detail: str) -> None:
        """Record honest degradation, best effort.

        A gap we could not even record is still a gap; this never raises,
        because failing here would mask the original failure.

        Args:
            component: What degraded.
            detail: Human-readable explanation.
        """
        if self._append is None or self._session.task_id is None:
            return
        event = JournalEvent(
            event_id=new_id(),
            task_id=self._session.task_id,
            occurred_at=utc_now(),
            event_type=EventType.TRACKING_DEGRADED,
            actor=Actor.RUNTIME,
            turn_id=self._session.turn_id,
            payload=DegradedPayload(component=component, detail=detail[:2000]),
        )
        try:
            await self._append(self._session.task_id, [event])
        except Exception:  # noqa: BLE001 — never mask the original failure
            pass
