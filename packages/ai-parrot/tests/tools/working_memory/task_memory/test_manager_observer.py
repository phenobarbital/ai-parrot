"""Observer integration with the real ToolManager (FEAT-538 / TASK-2984).

Three required cases from the task's Test Specification:

- ``test_branch_matrix`` — both dispatch branches and full-result mode,
  across successful and unsuccessful outcomes.
- ``test_guard_order`` — an authorization denial invokes no body and is
  ordered before any journal start; full-result locks release on
  cancellation.
- ``test_disabled_clone`` — disabled outputs and guard behaviour are
  unchanged, and concurrent manager clones cannot share turn capture.

Everything runs against the **real** ``ToolManager``. A stand-in would
prove nothing about guard ordering, which is the property most at risk
here: the whole point is that the observer sits *inside* the real
dispatch, after the real guards.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import pytest
from parrot.auth.permission import PermissionContext, UserSession
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.manager import ToolManager
from parrot.tools.working_memory.task_memory.context import turn_session
from parrot.tools.working_memory.task_memory.models import CallOutcome, EventType, JournalEvent, TaskScope
from parrot.tools.working_memory.task_memory.observer import InvocationObserver, ObserverMode

SCOPE = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")


def _permission_context() -> PermissionContext:
    """Build a real :class:`PermissionContext` for the guard-order cases.

    Constructed from the genuine ``UserSession`` shape rather than a stub,
    so the guard path under test is the real one.

    Returns:
        The context.
    """
    return PermissionContext(
        session=UserSession(user_id="u", tenant_id="t", roles=frozenset()),
        channel="test",
    )


class Journal:
    """Collects appended events."""

    def __init__(self) -> None:
        """Initialize an empty journal."""
        self.events: List[JournalEvent] = []

    async def append(self, task_id: str, events) -> None:
        """Record appended events.

        Args:
            task_id: Target task.
            events: Events to record.
        """
        self.events.extend(events)

    def types(self) -> List[EventType]:
        """Return appended event types in order."""
        return [e.event_type for e in self.events]


class Effect:
    """Records that a tool body actually ran."""

    def __init__(self) -> None:
        """Initialize with no effects."""
        self.ran: List[str] = []


class _EchoTool(AbstractTool):
    """A minimal AbstractTool for the second dispatch branch."""

    name: str = "echo_tool"
    description: str = "Echoes its input."

    def __init__(self, effect: Effect, *, fail: bool = False, hang: bool = False, **kwargs: Any) -> None:
        """Initialize the tool.

        Args:
            effect: Shared effect recorder.
            fail: Return an error ToolResult instead of succeeding.
            hang: Block forever, for the cancellation case.
            **kwargs: Forwarded to :class:`AbstractTool`.
        """
        super().__init__(**kwargs)
        self._effect = effect
        self._fail = fail
        self._hang = hang

    async def _execute(self, *args: Any, **kwargs: Any) -> Any:
        """Perform the tool's work.

        Returns:
            A :class:`ToolResult`.
        """
        self._effect.ran.append("echo_tool")
        if self._hang:
            await asyncio.sleep(3600)
        if self._fail:
            return ToolResult(success=False, status="error", error="boom", result=None)
        return ToolResult(status="success", result="echoed")


def _manager_with_definition(effect: Effect, *, fail: bool = False) -> ToolManager:
    """Build a manager holding one ``ToolDefinition``-style tool.

    Args:
        effect: Shared effect recorder.
        fail: Whether the function should raise.

    Returns:
        The manager.
    """
    manager = ToolManager()

    async def def_tool(value: str = "x") -> str:
        effect.ran.append("def_tool")
        if fail:
            raise ValueError("def_tool exploded")
        return f"def:{value}"

    manager.register_tool(
        name="def_tool",
        description="A plain function tool.",
        input_schema={"type": "object", "properties": {"value": {"type": "string"}}},
        function=def_tool,
    )
    return manager


def _observer(manager: ToolManager, session, journal: Journal, **kwargs: Any) -> InvocationObserver:
    """Install an observer on ``manager`` and return it.

    Args:
        manager: The manager to instrument.
        session: The turn session.
        journal: The journal to append to.
        **kwargs: Extra observer options.

    Returns:
        The installed observer.
    """
    observer = InvocationObserver(session, append=journal.append, **kwargs)
    manager.set_invocation_observer(observer)
    return observer


# ─────────────────────────────────────────────────────────────
# test_branch_matrix
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_branch_matrix_tool_definition_success_and_failure() -> None:
    """The ToolDefinition branch is observed on both success and failure."""
    journal, effect = Journal(), Effect()
    with turn_session(scope=SCOPE, task_id="t-1") as session:
        manager = _manager_with_definition(effect)
        observer = _observer(manager, session, journal)

        result = await manager.execute_tool("def_tool", {"value": "a"})
        assert result == "def:a"
        assert journal.types() == [EventType.TOOL_STARTED, EventType.TOOL_SUCCEEDED]
        assert observer.records[-1].outcome is CallOutcome.SUCCESS

    journal2, effect2 = Journal(), Effect()
    with turn_session(scope=SCOPE, task_id="t-1") as session:
        manager = _manager_with_definition(effect2, fail=True)
        observer = _observer(manager, session, journal2)

        with pytest.raises(ValueError, match="exploded"):
            await manager.execute_tool("def_tool", {})

        assert journal2.types() == [EventType.TOOL_STARTED, EventType.TOOL_FAILED]
        assert observer.records[-1].outcome is CallOutcome.ERROR
    assert effect2.ran == ["def_tool"], "the body ran exactly once"


@pytest.mark.asyncio
async def test_branch_matrix_abstract_tool_success_and_error() -> None:
    """The AbstractTool branch is observed on both outcomes."""
    journal, effect = Journal(), Effect()
    with turn_session(scope=SCOPE, task_id="t-1") as session:
        manager = ToolManager()
        manager.add_tool(_EchoTool(effect))
        _observer(manager, session, journal)

        result = await manager.execute_tool("echo_tool", {})
        assert result == "echoed"
        assert journal.types() == [EventType.TOOL_STARTED, EventType.TOOL_SUCCEEDED]

    # An error ToolResult: the manager raises ValueError in default mode.
    journal2, effect2 = Journal(), Effect()
    with turn_session(scope=SCOPE, task_id="t-1") as session:
        manager = ToolManager()
        manager.add_tool(_EchoTool(effect2, fail=True))
        _observer(manager, session, journal2)

        with pytest.raises(ValueError):
            await manager.execute_tool("echo_tool", {})

        assert journal2.types() == [EventType.TOOL_STARTED, EventType.TOOL_FAILED]
    assert effect2.ran == ["echo_tool"], "the body ran exactly once, not twice"


@pytest.mark.asyncio
async def test_branch_matrix_full_result_mode_is_observed_once() -> None:
    """``return_tool_result=True`` is observed, and executes exactly once."""
    journal, effect = Journal(), Effect()
    with turn_session(scope=SCOPE, task_id="t-1") as session:
        manager = ToolManager()
        manager.add_tool(_EchoTool(effect))
        _observer(manager, session, journal)

        envelope = await manager.execute_tool("echo_tool", {}, return_tool_result=True)

    assert isinstance(envelope, ToolResult)
    assert envelope.status == "success"
    assert effect.ran == ["echo_tool"], "full-result mode must not re-execute the tool"
    assert journal.types() == [EventType.TOOL_STARTED, EventType.TOOL_SUCCEEDED]


@pytest.mark.asyncio
async def test_branch_matrix_full_result_definition_branch() -> None:
    """Full-result mode on the ToolDefinition branch is observed once too."""
    journal, effect = Journal(), Effect()
    with turn_session(scope=SCOPE, task_id="t-1") as session:
        manager = _manager_with_definition(effect)
        _observer(manager, session, journal)

        envelope = await manager.execute_tool("def_tool", {"value": "z"}, return_tool_result=True)

    assert isinstance(envelope, ToolResult)
    assert envelope.result == "def:z"
    assert effect.ran == ["def_tool"]
    assert journal.types() == [EventType.TOOL_STARTED, EventType.TOOL_SUCCEEDED]


@pytest.mark.asyncio
async def test_branch_matrix_unknown_tool_never_starts() -> None:
    """An unknown tool is an unsuccessful dispatch, not a failed execution."""
    journal = Journal()
    with turn_session(scope=SCOPE, task_id="t-1") as session:
        manager = ToolManager()
        observer = _observer(manager, session, journal)

        result = await manager.execute_tool("no_such_tool", {})

    assert isinstance(result, ToolResult)
    assert result.status == "not_found"
    assert EventType.TOOL_STARTED not in journal.types(), "no fictitious start"
    assert observer.records[-1].executed is False


@pytest.mark.asyncio
async def test_branch_matrix() -> None:
    """Required aggregate case: both branches and full-result mode, both outcomes."""
    await test_branch_matrix_tool_definition_success_and_failure()
    await test_branch_matrix_abstract_tool_success_and_error()
    await test_branch_matrix_full_result_mode_is_observed_once()
    await test_branch_matrix_full_result_definition_branch()
    await test_branch_matrix_unknown_tool_never_starts()


# ─────────────────────────────────────────────────────────────
# test_guard_order
# ─────────────────────────────────────────────────────────────


class _DenyingResolver:
    """A Layer 2 resolver that refuses everything."""

    async def can_execute(self, permission_context: Any, tool_name: str, required: Any) -> bool:
        """Refuse every call.

        Returns:
            ``False``, always.
        """
        return False

    async def get_user_permissions(self, *args: Any, **kwargs: Any) -> Any:
        """Return no permissions."""
        return []


@pytest.mark.asyncio
async def test_guard_order_denial_invokes_no_body_and_no_start() -> None:
    """A denial is ordered before the body AND before any journal start.

    Both halves matter. The body must not run, and the journal must not
    record a start for a call that a guard was about to refuse — a
    fictitious start would claim an execution that never happened.
    """
    journal, effect = Journal(), Effect()
    with turn_session(scope=SCOPE, task_id="t-1") as session:
        manager = _manager_with_definition(effect)
        manager._resolver = _DenyingResolver()
        observer = _observer(manager, session, journal)

        result = await manager.execute_tool("def_tool", {}, permission_context=_permission_context())

    assert isinstance(result, ToolResult)
    assert result.status == "forbidden"
    assert effect.ran == [], "the body must never run on a denial"
    assert EventType.TOOL_STARTED not in journal.types(), "a denial must not record a start"
    assert observer.records[-1].executed is False
    assert observer.records[-1].outcome in (CallOutcome.DENIED, CallOutcome.NOT_EXECUTED)


@pytest.mark.asyncio
async def test_guard_order_start_is_written_before_the_body_runs() -> None:
    """``tool_started`` reaches the journal before the body executes."""
    journal = Journal()
    observed_at_body: List[List[EventType]] = []

    with turn_session(scope=SCOPE, task_id="t-1") as session:
        manager = ToolManager()

        async def probing_tool() -> str:
            observed_at_body.append(journal.types())
            return "ok"

        manager.register_tool(
            name="probing_tool",
            description="Observes the journal from inside its own body.",
            input_schema={"type": "object", "properties": {}},
            function=probing_tool,
        )
        _observer(manager, session, journal)
        await manager.execute_tool("probing_tool", {})

    assert observed_at_body == [[EventType.TOOL_STARTED]], "the start must already be journalled when the body runs"
    assert journal.types() == [EventType.TOOL_STARTED, EventType.TOOL_SUCCEEDED]


@pytest.mark.asyncio
async def test_guard_order_cancellation_releases_the_full_result_lock() -> None:
    """A cancelled full-result call records cancellation and frees the lock.

    If the FEAT-536 lock leaked on cancellation, the very next
    full-result call on the same tool instance would hang — so the second
    call completing is the real assertion here.
    """
    journal, effect = Journal(), Effect()
    with turn_session(scope=SCOPE, task_id="t-1") as session:
        manager = ToolManager()
        hanging = _EchoTool(effect, hang=True)
        manager.add_tool(hanging)
        _observer(manager, session, journal)

        task = asyncio.create_task(manager.execute_tool("echo_tool", {}, return_tool_result=True))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert EventType.TOOL_CANCELLED in journal.types()

        # The lock must have been released: swap in a non-hanging tool on
        # the SAME manager and confirm a full-result call still completes.
        hanging._hang = False
        result = await asyncio.wait_for(manager.execute_tool("echo_tool", {}, return_tool_result=True), timeout=5)
        assert isinstance(result, ToolResult)


@pytest.mark.asyncio
async def test_guard_order_cancellation_is_not_swallowed() -> None:
    """The CancelledError propagates; bookkeeping never converts it to a result."""
    journal, effect = Journal(), Effect()
    with turn_session(scope=SCOPE, task_id="t-1") as session:
        manager = ToolManager()
        manager.add_tool(_EchoTool(effect, hang=True))
        _observer(manager, session, journal)

        task = asyncio.create_task(manager.execute_tool("echo_tool", {}))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_guard_order_durable_failure_prevents_the_body() -> None:
    """A durable start failure stops the body from ever running."""
    effect = Effect()

    class FailingJournal(Journal):
        async def append(self, task_id: str, events) -> None:
            for event in events:
                if event.event_type is EventType.TOOL_STARTED:
                    raise RuntimeError("journal down")
            await super().append(task_id, events)

    journal = FailingJournal()
    with turn_session(scope=SCOPE, task_id="t-1") as session:
        manager = _manager_with_definition(effect)
        _observer(manager, session, journal, mode=ObserverMode.DURABLE)

        from parrot.tools.working_memory.task_memory.models import TaskMemoryUnavailable

        with pytest.raises(TaskMemoryUnavailable):
            await manager.execute_tool("def_tool", {})

    assert effect.ran == [], "fail-closed: the body must not have run"


@pytest.mark.asyncio
async def test_guard_order() -> None:
    """Required aggregate case: denial precedes body and start; locks release."""
    await test_guard_order_denial_invokes_no_body_and_no_start()
    await test_guard_order_start_is_written_before_the_body_runs()
    await test_guard_order_cancellation_releases_the_full_result_lock()
    await test_guard_order_cancellation_is_not_swallowed()
    await test_guard_order_durable_failure_prevents_the_body()


# ─────────────────────────────────────────────────────────────
# test_disabled_clone
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_disabled_clone_no_observer_is_byte_identical() -> None:
    """With no observer installed, dispatch behaves exactly as before."""
    effect = Effect()
    manager = _manager_with_definition(effect)
    assert manager.invocation_observer is None

    assert await manager.execute_tool("def_tool", {"value": "q"}) == "def:q"

    envelope = await manager.execute_tool("def_tool", {"value": "q"}, return_tool_result=True)
    assert isinstance(envelope, ToolResult) and envelope.result == "def:q"

    missing = await manager.execute_tool("nope", {})
    assert isinstance(missing, ToolResult) and missing.status == "not_found"

    failing = _manager_with_definition(Effect(), fail=True)
    with pytest.raises(ValueError):
        await failing.execute_tool("def_tool", {})


@pytest.mark.asyncio
async def test_disabled_clone_guard_behaviour_unchanged_when_disabled() -> None:
    """Guard denials return their usual envelope with no observer."""
    effect = Effect()
    manager = _manager_with_definition(effect)
    manager._resolver = _DenyingResolver()

    result = await manager.execute_tool("def_tool", {}, permission_context=_permission_context())
    assert isinstance(result, ToolResult) and result.status == "forbidden"
    assert effect.ran == []


@pytest.mark.asyncio
async def test_disabled_clone_does_not_inherit_the_observer() -> None:
    """A clone starts unobserved even though it shares tool instances.

    Clones share tools but own their mutable state. Inheriting the
    observer would let one clone's turn capture collect another clone's
    calls.
    """
    journal, effect = Journal(), Effect()
    with turn_session(scope=SCOPE, task_id="t-1") as session:
        manager = _manager_with_definition(effect)
        observer = _observer(manager, session, journal)

        clone = manager.clone()
        assert clone.invocation_observer is None, "a clone must not inherit turn capture"

        await clone.execute_tool("def_tool", {})
        assert observer.records == (), "the clone's call must not land in the parent's capture"
        assert journal.events == []

        await manager.execute_tool("def_tool", {})
        assert len(observer.records) == 1


@pytest.mark.asyncio
async def test_disabled_clone_concurrent_clones_capture_independently() -> None:
    """Two observed clones running concurrently never mix their captures."""
    effect = Effect()
    base = _manager_with_definition(effect)

    journal_a, journal_b = Journal(), Journal()

    async def run(manager: ToolManager, journal: Journal, task_id: str, n: int) -> int:
        with turn_session(scope=SCOPE, task_id=task_id) as session:
            observer = InvocationObserver(session, append=journal.append)
            manager.set_invocation_observer(observer)
            for _ in range(n):
                await manager.execute_tool("def_tool", {})
            return len(observer.records)

    clone_a, clone_b = base.clone(), base.clone()
    counts = await asyncio.gather(
        run(clone_a, journal_a, "t-a", 3),
        run(clone_b, journal_b, "t-b", 5),
    )

    assert counts == [3, 5], "each clone captured exactly its own calls"
    assert {e.task_id for e in journal_a.events} == {"t-a"}
    assert {e.task_id for e in journal_b.events} == {"t-b"}


@pytest.mark.asyncio
async def test_disabled_clone_concurrent_dispatches_do_not_share_observation() -> None:
    """Two concurrent dispatches on ONE manager keep separate observations.

    The per-dispatch marker is a local object, not manager state. If it
    were instance state, a denial racing a real execution could mark the
    denial as "executed" and suppress its ``not_executed`` record.
    """
    journal, effect = Journal(), Effect()
    with turn_session(scope=SCOPE, task_id="t-1") as session:
        manager = _manager_with_definition(effect)
        observer = _observer(manager, session, journal)

        results = await asyncio.gather(
            manager.execute_tool("def_tool", {}),
            manager.execute_tool("missing_tool", {}),
            manager.execute_tool("def_tool", {}),
        )

    assert results[0] == "def:x" and results[2] == "def:x"
    assert isinstance(results[1], ToolResult) and results[1].status == "not_found"

    executed = [r for r in observer.records if r.executed]
    not_executed = [r for r in observer.records if not r.executed]
    assert len(executed) == 2, "both real calls recorded as executed"
    assert len(not_executed) == 1, "the unknown tool recorded as not executed"
    assert effect.ran == ["def_tool", "def_tool"]


@pytest.mark.asyncio
async def test_disabled_clone() -> None:
    """Required aggregate case: disabled behaviour unchanged; clones stay isolated."""
    await test_disabled_clone_no_observer_is_byte_identical()
    await test_disabled_clone_guard_behaviour_unchanged_when_disabled()
    await test_disabled_clone_does_not_inherit_the_observer()
    await test_disabled_clone_concurrent_clones_capture_independently()
    await test_disabled_clone_concurrent_dispatches_do_not_share_observation()
