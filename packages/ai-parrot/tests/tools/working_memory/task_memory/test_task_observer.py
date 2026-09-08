"""The canonical invocation observer (FEAT-538 / TASK-2983).

Four required cases from the task's Test Specification:

- ``test_start_failure`` — a durable append failure prevents the
  side-effect counter from being invoked at all.
- ``test_terminal_failure`` — an effect followed by a journal failure
  returns unknown/degraded, never a safe-to-retry success.
- ``test_read_only`` — repeated recall/listing changes neither the
  journal sequence nor task activity.
- ``test_collector`` — exactly one normalized ``ToolInvocation`` per
  observed physical call is available for the conversation save.

``test_start_failure`` uses a real **side-effect counter** rather than
asserting on a mock's call list: the property under test is that the
effect never happened, and only something that would actually record
having happened can demonstrate that.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence

import pytest
from parrot.memory.compaction.models import ToolInvocation, ToolStatus
from parrot.tools.working_memory.task_memory.context import turn_session
from parrot.tools.working_memory.task_memory.models import (
    CallOutcome,
    EventType,
    EvidenceRef,
    JournalEvent,
    TaskMemoryUnavailable,
    TaskScope,
)
from parrot.tools.working_memory.task_memory.observer import READ_ONLY_TOOLS, InvocationObserver, ObserverMode

SCOPE = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")


class RecordingJournal:
    """A journal that records appends, and can be made to fail on cue."""

    def __init__(self) -> None:
        """Initialize an empty journal."""
        self.events: List[JournalEvent] = []
        self.fail_on: set = set()
        self.seq = 0

    async def append(self, task_id: str, events: Sequence[JournalEvent]) -> None:
        """Append events, failing for any configured event type.

        Args:
            task_id: Target task.
            events: The events to append.

        Raises:
            RuntimeError: When an event's type is in ``fail_on``.
        """
        for event in events:
            if event.event_type in self.fail_on:
                raise RuntimeError(f"journal is unavailable for {event.event_type.value}")
        for event in events:
            self.seq += 1
            self.events.append(event.model_copy(update={"seq": self.seq}))

    def types(self) -> List[EventType]:
        """Return the appended event types, in order."""
        return [e.event_type for e in self.events]


class SideEffectCounter:
    """A stand-in for a tool with a real external effect.

    Records each invocation rather than merely counting, so a test can
    tell "ran once, result lost" from "ran twice" — which a bare counter
    cannot.
    """

    def __init__(self) -> None:
        """Initialize with no recorded effects."""
        self.effects: List[str] = []

    async def charge(self, amount: str = "10.00") -> str:
        """Perform the effect.

        Args:
            amount: Amount charged.

        Returns:
            A receipt string.
        """
        self.effects.append(amount)
        return f"charged {amount}"

    @property
    def count(self) -> int:
        """How many times the effect actually happened."""
        return len(self.effects)


def _session(task_id: Optional[str] = "t-1"):
    """Open a turn session bound to the standard scope.

    Args:
        task_id: Selected task, or ``None`` for no selection.

    Returns:
        The session context manager.
    """
    return turn_session(scope=SCOPE, task_id=task_id, turn_id="turn-1")


# ─────────────────────────────────────────────────────────────
# test_start_failure
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_failure_durable_mode_prevents_the_effect() -> None:
    """A failed durable ``tool_started`` stops the call from ever running.

    Asserted with a real side-effect counter: the point is not that an
    exception was raised, it is that the external effect NEVER HAPPENED.
    An untracked effect is worse than a refused one.
    """
    journal = RecordingJournal()
    journal.fail_on = {EventType.TOOL_STARTED}
    effect = SideEffectCounter()

    with _session() as session:
        observer = InvocationObserver(session, append=journal.append, mode=ObserverMode.DURABLE)

        with pytest.raises(TaskMemoryUnavailable, match="refusing to run it untracked"):
            call = await observer.begin("charge_card")
            await effect.charge()  # must never be reached
            await observer.finish(call, value="ok")

    assert effect.count == 0, "the effect ran despite the start not being persisted"
    assert journal.events == [], "nothing should have been journalled"


@pytest.mark.asyncio
async def test_start_failure_best_effort_runs_but_reports_degraded() -> None:
    """Best-effort mode is an explicit opt-in, and it never hides the degradation."""
    journal = RecordingJournal()
    journal.fail_on = {EventType.TOOL_STARTED}
    effect = SideEffectCounter()

    with _session() as session:
        observer = InvocationObserver(session, append=journal.append, mode=ObserverMode.BEST_EFFORT)
        call = await observer.begin("charge_card")
        assert call.degraded is True
        assert call.journalled is False

        await effect.charge()
        outcome = await observer.finish(call, value="ok")

    assert effect.count == 1, "best-effort mode should still run the call"
    assert outcome.outcome is CallOutcome.SUCCESS
    assert EventType.TRACKING_DEGRADED in journal.types(), "degradation must be recorded, not hidden"
    assert session.records[0].degraded is True


@pytest.mark.asyncio
async def test_start_failure_start_precedes_the_attempt() -> None:
    """``tool_started`` reaches the journal before the effect happens."""
    journal = RecordingJournal()
    effect = SideEffectCounter()

    with _session() as session:
        observer = InvocationObserver(session, append=journal.append)
        call = await observer.begin("charge_card")

        # At this instant the start is durable and the effect has not run.
        assert journal.types() == [EventType.TOOL_STARTED]
        assert effect.count == 0

        await effect.charge()
        await observer.finish(call, value="ok")

    assert journal.types() == [EventType.TOOL_STARTED, EventType.TOOL_SUCCEEDED]


@pytest.mark.asyncio
async def test_start_failure_denials_get_no_fictitious_start() -> None:
    """A guard denial never produces a ``tool_started``.

    Recording a start for a call that never ran would claim an execution
    that did not happen and corrupt the attempt counts.
    """
    from parrot.tools.abstract import ToolResult

    journal = RecordingJournal()
    with _session() as session:
        observer = InvocationObserver(session, append=journal.append)
        outcome = await observer.not_executed(
            "charge_card",
            value=ToolResult(success=False, status="forbidden", error="policy denied", result=None),
        )

    assert outcome.executed is False
    assert EventType.TOOL_STARTED not in journal.types()
    payloads = [e.payload for e in journal.events]
    assert payloads and payloads[0].executed is False
    assert payloads[0].counted is False, "a call that never ran is not a physical attempt"


@pytest.mark.asyncio
async def test_start_failure() -> None:
    """Required aggregate case: a durable start failure prevents the effect."""
    await test_start_failure_durable_mode_prevents_the_effect()
    await test_start_failure_best_effort_runs_but_reports_degraded()
    await test_start_failure_start_precedes_the_attempt()
    await test_start_failure_denials_get_no_fictitious_start()


# ─────────────────────────────────────────────────────────────
# test_terminal_failure
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_terminal_failure_returns_unknown_not_success() -> None:
    """An effect plus a failed terminal write yields UNKNOWN, never success.

    This is the case that makes a crash distinguishable from a clean run.
    Reporting success here would invite retrying an effect that already
    happened.
    """
    journal = RecordingJournal()
    journal.fail_on = {EventType.TOOL_SUCCEEDED}
    effect = SideEffectCounter()

    with _session() as session:
        observer = InvocationObserver(session, append=journal.append)
        call = await observer.begin("charge_card")
        await effect.charge()
        outcome = await observer.finish(call, value="charged 10.00")

    assert effect.count == 1, "the effect DID happen"
    assert outcome.outcome is CallOutcome.UNKNOWN, "must never claim success"
    assert outcome.executed is True, "and must not pretend it did not run"
    assert "do not retry automatically" in (outcome.error or "")

    # The start is still durable, and the degradation is recorded.
    assert EventType.TOOL_STARTED in journal.types()
    assert EventType.TRACKING_DEGRADED in journal.types()


@pytest.mark.asyncio
async def test_terminal_failure_error_outcome_is_preserved() -> None:
    """A genuine tool error is recorded as a failure, not as unknown."""
    journal = RecordingJournal()
    with _session() as session:
        observer = InvocationObserver(session, append=journal.append)
        call = await observer.begin("charge_card")
        outcome = await observer.finish(call, exception=ValueError("card declined"))

    assert outcome.outcome is CallOutcome.ERROR
    assert journal.types() == [EventType.TOOL_STARTED, EventType.TOOL_FAILED]


@pytest.mark.asyncio
async def test_terminal_failure_cancellation_is_recorded_and_propagates() -> None:
    """Cancellation is recorded, then re-raised by the caller."""
    journal = RecordingJournal()
    with _session() as session:
        observer = InvocationObserver(session, append=journal.append)
        call = await observer.begin("slow_tool")
        await observer.cancelled(call)

    assert journal.types() == [EventType.TOOL_STARTED, EventType.TOOL_CANCELLED]
    record = session.records[0]
    assert record.outcome is CallOutcome.CANCELLED
    assert record.outcome.is_resolved is False, "cancelled stays unresolved"


@pytest.mark.asyncio
async def test_terminal_failure_cancellation_recording_never_suppresses() -> None:
    """A journal failure while recording a cancellation does not raise.

    Bookkeeping must never suppress a ``CancelledError``: swallowing one
    to finish recording would turn a cancelled call into a completed one.
    """
    journal = RecordingJournal()
    journal.fail_on = {EventType.TOOL_CANCELLED}
    with _session() as session:
        observer = InvocationObserver(session, append=journal.append)
        call = await observer.begin("slow_tool")
        await observer.cancelled(call)  # must not raise

    assert session.records[0].outcome is CallOutcome.CANCELLED


@pytest.mark.asyncio
async def test_terminal_failure_counts_each_physical_attempt_once() -> None:
    """Exactly one terminal event counts an attempt; a parent aggregate does not."""
    journal = RecordingJournal()
    with _session() as session:
        observer = InvocationObserver(session, append=journal.append)

        parent = await observer.begin("execution_plan")
        child = await observer.begin("charge_card", parent_call_id=parent.call_id)
        await observer.finish(child, value="ok")
        await observer.finish(parent, value="plan done")

    counted = [e.payload for e in journal.events if getattr(e.payload, "counted", False)]
    assert len(counted) == 1, "only the physical child attempt counts"
    assert counted[0].tool_name == "charge_card"
    assert counted[0].call_id == child.call_id


@pytest.mark.asyncio
async def test_terminal_failure() -> None:
    """Required aggregate case: a failed terminal write never reports success."""
    await test_terminal_failure_returns_unknown_not_success()
    await test_terminal_failure_error_outcome_is_preserved()
    await test_terminal_failure_cancellation_is_recorded_and_propagates()
    await test_terminal_failure_cancellation_recording_never_suppresses()
    await test_terminal_failure_counts_each_physical_attempt_once()


# ─────────────────────────────────────────────────────────────
# test_read_only
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_read_only_recall_and_listing_append_nothing() -> None:
    """Observing a read-only tool changes neither sequence nor activity."""
    journal = RecordingJournal()
    with _session() as session:
        observer = InvocationObserver(session, append=journal.append)

        for _ in range(5):
            for tool in ("wm_recall_task", "wm_list_task_events", "wm_list_task_artifacts"):
                call = await observer.begin(tool)
                await observer.finish(call, value={"ok": True})

    assert journal.events == [], "a read-only tool must append nothing at all"
    assert journal.seq == 0, "the journal sequence must not move"
    # But the calls WERE captured for the conversation turn.
    assert len(session.records) == 15


@pytest.mark.asyncio
async def test_read_only_a_mutating_tool_still_appends() -> None:
    """The exemption is per tool, not a blanket switch."""
    journal = RecordingJournal()
    with _session() as session:
        observer = InvocationObserver(session, append=journal.append)

        call = await observer.begin("wm_recall_task")
        await observer.finish(call, value={})
        assert journal.events == []

        call = await observer.begin("wm_store")
        await observer.finish(call, value={"key": "sales"})

    assert journal.types() == [EventType.TOOL_STARTED, EventType.TOOL_SUCCEEDED]


@pytest.mark.asyncio
async def test_read_only_set_covers_every_read_command() -> None:
    """Every read-only command named by the spec is exempt."""
    assert {"wm_recall_task", "wm_list_task_events", "wm_list_task_artifacts"} <= READ_ONLY_TOOLS


@pytest.mark.asyncio
async def test_read_only_no_task_selected_journals_nothing() -> None:
    """With no task selected there is nothing to append to."""
    journal = RecordingJournal()
    with _session(task_id=None) as session:
        observer = InvocationObserver(session, append=journal.append)
        call = await observer.begin("wm_store")
        await observer.finish(call, value="ok")

    assert journal.events == []
    assert len(session.records) == 1, "the call is still captured for the turn"


@pytest.mark.asyncio
async def test_read_only() -> None:
    """Required aggregate case: repeated reads change neither sequence nor activity."""
    await test_read_only_recall_and_listing_append_nothing()
    await test_read_only_a_mutating_tool_still_appends()
    await test_read_only_set_covers_every_read_command()
    await test_read_only_no_task_selected_journals_nothing()


# ─────────────────────────────────────────────────────────────
# test_collector
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_collector_one_record_per_physical_call() -> None:
    """Exactly one record per observed call, in dispatch order."""
    journal = RecordingJournal()
    with _session() as session:
        observer = InvocationObserver(session, append=journal.append)
        for name in ("wm_store", "charge_card", "wm_store"):
            call = await observer.begin(name)
            await observer.finish(call, value="ok")

    records = list(observer.records)
    assert [r.tool_name for r in records] == ["wm_store", "charge_card", "wm_store"]
    assert len({r.call_id for r in records}) == 3, "each physical call gets its own identity"


@pytest.mark.asyncio
async def test_collector_carries_the_canonical_tool_invocation() -> None:
    """The record carries the compaction ``ToolInvocation`` verbatim.

    The enabled path must REPLACE the legacy ``AIMessage.tool_calls``
    conversion, not append to it, so a turn cannot list each call twice.
    """
    journal = RecordingJournal()
    invocation = ToolInvocation(
        tool_name="wm_store",
        input={"key": "sales"},
        output="stored",
        status=ToolStatus.COMPLETED,
        elapsed_ms=12,
    )
    with _session() as session:
        observer = InvocationObserver(session, append=journal.append)
        call = await observer.begin("wm_store")
        await observer.finish(call, value="stored", invocation=invocation)

    record = observer.records[0]
    assert record.invocation is invocation, "the canonical payload is carried, not rebuilt"
    assert record.invocation.tool_name == "wm_store"
    assert record.invocation.status is ToolStatus.COMPLETED


@pytest.mark.asyncio
async def test_collector_nested_calls_keep_their_own_identity() -> None:
    """A nested plan call is distinguishable from its parent aggregate."""
    journal = RecordingJournal()
    with _session() as session:
        observer = InvocationObserver(session, append=journal.append)
        parent = await observer.begin("execution_plan")
        child_a = await observer.begin("fetch", parent_call_id=parent.call_id)
        await observer.finish(child_a, value="a")
        child_b = await observer.begin("fetch", parent_call_id=parent.call_id)
        await observer.finish(child_b, value="b")
        await observer.finish(parent, value="done")

    by_id = {r.call_id: r for r in observer.records}
    assert len(by_id) == 3
    assert by_id[parent.call_id].parent_call_id is None
    assert by_id[child_a.call_id].parent_call_id == parent.call_id
    assert by_id[child_b.call_id].parent_call_id == parent.call_id
    assert child_a.call_id != child_b.call_id, "two attempts of the same tool are distinct"


@pytest.mark.asyncio
async def test_collector_retains_artifact_receipts() -> None:
    """Artifact receipts survive on the record for post-dispatch correlation.

    This is the Phase 0 hazard: ``PlanToolNode._store`` runs after the
    manager has reset its invocation context, so the receipt has to live
    on something that outlives the dispatch.
    """
    journal = RecordingJournal()
    ref = EvidenceRef(artifact_id="art-1", version=2)
    with _session() as session:
        observer = InvocationObserver(session, append=journal.append)
        call = await observer.begin("plan_node")
        await observer.finish(call, value="ok", artifact_receipts=[ref])

        # The receipt is still retrievable AFTER the dispatch finished.
        retained = session.receipt(call.call_id)

    assert retained is not None
    assert ref in retained.artifact_receipts
    payload = journal.events[-1].payload
    assert ref in payload.artifact_refs


@pytest.mark.asyncio
async def test_collector_records_survive_a_failed_journal() -> None:
    """The turn's records are complete even when journalling degraded."""
    journal = RecordingJournal()
    journal.fail_on = {EventType.TOOL_STARTED}
    with _session() as session:
        observer = InvocationObserver(session, append=journal.append, mode=ObserverMode.BEST_EFFORT)
        call = await observer.begin("wm_store")
        await observer.finish(call, value="ok")

    assert len(observer.records) == 1, "the conversation turn still gets its record"
    assert observer.records[0].degraded is True


@pytest.mark.asyncio
async def test_collector_works_without_a_journal_at_all() -> None:
    """With no journal the collector still captures records.

    This is the observed-but-disabled configuration: the conversation
    turn benefits from canonical capture even when no task is tracked.
    """
    with _session(task_id=None) as session:
        observer = InvocationObserver(session, append=None)
        call = await observer.begin("wm_store")
        outcome = await observer.finish(call, value="ok")

    assert outcome.outcome is CallOutcome.SUCCESS
    assert len(observer.records) == 1


@pytest.mark.asyncio
async def test_collector() -> None:
    """Required aggregate case: exactly one normalized invocation per physical call."""
    await test_collector_one_record_per_physical_call()
    await test_collector_carries_the_canonical_tool_invocation()
    await test_collector_nested_calls_keep_their_own_identity()
    await test_collector_retains_artifact_receipts()
    await test_collector_records_survive_a_failed_journal()
    await test_collector_works_without_a_journal_at_all()
