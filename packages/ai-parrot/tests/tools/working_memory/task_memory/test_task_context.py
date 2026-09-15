"""Unit tests for the per-turn task context (FEAT-538 / TASK-2981).

Three required cases from the task's Test Specification:

- ``test_child_publish`` — a successful running declaration made inside a
  child task is visible to later siblings through the shared registry.
- ``test_attribution`` — two declarations before a dispatch yield
  ``ambiguous``, and prior dispatch snapshots never change retroactively.
- ``test_reset`` — exceptions, nested invocations and cancellation reset
  the ContextVars without leaking scope.

Each is implemented as a group of focused functions plus an aggregate
carrying the required name, so a failure names the invariant that broke.

The spec's §4 *Context* row is covered here too: same-turn declaration
barriers, zero/one/multiple declarations, child task publication, thread
propagation, finally reset, concurrent users/tasks, and the plan
post-dispatch storage receipt.
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from parrot.tools.working_memory.task_memory.context import (
    CURRENT_CALL,
    MAX_DECLARED_STEPS_PER_TURN,
    RETAINED_PRODUCER,
    TASK_CONTEXT,
    StaleTurnContext,
    TurnContextEnvelope,
    TurnTaskSession,
    async_turn_session,
    current_call_id,
    current_session,
    producer_call_id,
    run_in_thread,
    spawn_task,
    turn_session,
)
from parrot.tools.working_memory.task_memory.models import (
    Attribution,
    CallOutcome,
    EventType,
    EvidenceRef,
    LimitExceeded,
    Limits,
    ScopeViolation,
    TaskScope,
)
from pydantic import ValidationError

pytestmark = pytest.mark.asyncio

# ─────────────────────────────────────────────────────────────
# Local fixtures (the shared fixture task is not yet complete)
# ─────────────────────────────────────────────────────────────

SCOPE_A = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")
SCOPE_B = TaskScope(chatbot_id="bot-a", user_id="user-2", session_id="sess-1")


@pytest.fixture()
def session() -> TurnTaskSession:
    """Return a deterministic turn session for task ``t-1``."""
    return TurnTaskSession(SCOPE_A, turn_id="turn-1", task_id="t-1", plan_revision=3)


@pytest.fixture(autouse=True)
def _no_context_leak():
    """Fail loudly if a test leaves a ContextVar set.

    The whole module is about not leaking scope, so the test suite holds
    itself to the same rule.
    """
    yield
    assert TASK_CONTEXT.get() is None, "TASK_CONTEXT leaked out of a test"
    assert CURRENT_CALL.get() is None, "CURRENT_CALL leaked out of a test"
    assert RETAINED_PRODUCER.get() is None, "RETAINED_PRODUCER leaked out of a test"


# ─────────────────────────────────────────────────────────────
# Child publication through the shared session
# ─────────────────────────────────────────────────────────────


async def test_child_publish_declaration_reaches_later_siblings(session: TurnTaskSession) -> None:
    """A declaration made in one child task is seen by a later sibling."""
    started = asyncio.Event()

    async def declaring_child() -> None:
        current_session().declare("s-clean")
        started.set()

    async def observing_child() -> tuple:
        await started.wait()
        return current_session().snapshot().declared_step_ids

    with turn_session(SCOPE_A, session=session):
        declarer = spawn_task(declaring_child())
        observer = spawn_task(observing_child())
        await declarer
        observed = await observer

    assert observed == ("s-clean",), "the shared session is what publishes, not the ContextVar"


async def test_child_publish_rebinding_the_contextvar_does_not_publish(session: TurnTaskSession) -> None:
    """Assigning TASK_CONTEXT in a child is invisible to the parent.

    This is the failure mode the session object exists to avoid; the test
    pins it so nobody "simplifies" the design back into a bare ContextVar.
    """
    other = TurnTaskSession(SCOPE_A, turn_id="turn-2")

    async def rebinding_child() -> None:
        TASK_CONTEXT.set(other)
        assert current_session() is other

    with turn_session(SCOPE_A, session=session):
        await spawn_task(rebinding_child())
        assert current_session() is session, "a child's ContextVar assignment must not reach the parent"


async def test_child_publish_survives_many_concurrent_declarers(session: TurnTaskSession) -> None:
    """Concurrent declarations from many children all land in the registry."""

    async def declare(step_id: str) -> None:
        await asyncio.sleep(0)
        current_session().declare(step_id)

    with turn_session(SCOPE_A, session=session):
        await asyncio.gather(*(declare(f"s-{n}") for n in range(20)))
        assert set(session.declared_step_ids) == {f"s-{n}" for n in range(20)}
        assert len(session.declared_step_ids) == 20, "no declaration was lost to a race"


async def test_child_publish_from_thread_work(session: TurnTaskSession) -> None:
    """Thread work sees the same session and can publish into it."""

    def declare_in_thread() -> str:
        assert current_session() is session, "context must be copied into the thread"
        current_session().declare("s-thread")
        return threading.current_thread().name

    with turn_session(SCOPE_A, session=session):
        thread_name = await run_in_thread(declare_in_thread)
        assert thread_name != threading.current_thread().name, "must actually run off the main thread"
        assert session.declared_step_ids == ("s-thread",)


async def test_child_publish_bare_threadpool_needs_the_helper(session: TurnTaskSession) -> None:
    """A bare ThreadPoolExecutor loses the context — hence run_in_thread.

    Documents *why* the helper exists rather than assuming callers know.
    """
    with turn_session(SCOPE_A, session=session):
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            seen = await loop.run_in_executor(pool, current_session)
        assert seen is None, "ThreadPoolExecutor.submit does not propagate contextvars"

        # The helper does.
        assert await run_in_thread(current_session) is session


async def test_child_publish_declaration_is_idempotent(session: TurnTaskSession) -> None:
    """Re-declaring a step keeps its position and does not create ambiguity.

    A retried step update must not reorder the registry: if it did, a
    later dispatch's ``declared_step_ids`` would depend on retry timing,
    and attribution would stop being deterministic.
    """
    session.declare("s-clean")
    session.declare("s-clean")
    assert session.declared_step_ids == ("s-clean",)
    assert session.snapshot().attribution is Attribution.DECLARED

    # Re-declaring an *earlier* step must not move it behind a later one.
    session.declare("s-report")
    assert session.declared_step_ids == ("s-clean", "s-report")
    session.declare("s-clean")
    assert session.declared_step_ids == ("s-clean", "s-report"), "a retry must not reorder the registry"


async def test_child_publish_declaration_order_is_stable(session: TurnTaskSession) -> None:
    """Declarations report in declaration order, not hash order."""
    for step_id in ("s-c", "s-a", "s-b"):
        session.declare(step_id)
    assert session.declared_step_ids == ("s-c", "s-a", "s-b")

    # Re-declaring any of them leaves the order untouched.
    for step_id in ("s-a", "s-c", "s-b"):
        session.declare(step_id)
    assert session.declared_step_ids == ("s-c", "s-a", "s-b")


async def test_child_publish_registry_is_bounded(session: TurnTaskSession) -> None:
    """A runaway loop cannot grow the declaration registry without limit."""
    for n in range(MAX_DECLARED_STEPS_PER_TURN):
        session.declare(f"s-{n}")
    with pytest.raises(LimitExceeded) as excinfo:
        session.declare("one-too-many")
    assert excinfo.value.limit == MAX_DECLARED_STEPS_PER_TURN

    with pytest.raises(ValueError):
        session.undeclare("s-0") and session.declare("")
    with pytest.raises(ValueError):
        session.declare("x" * (Limits.MAX_IDENTIFIER + 1))


async def test_child_publish_sessions_are_isolated_per_user(session: TurnTaskSession) -> None:
    """Two concurrent turns for different users never see each other."""
    other = TurnTaskSession(SCOPE_B, turn_id="turn-b", task_id="t-2")

    async def run(active: TurnTaskSession, step_id: str) -> tuple:
        with turn_session(active.scope, session=active):
            await asyncio.sleep(0)
            current_session().declare(step_id)
            await asyncio.sleep(0)
            return current_session().snapshot().declared_step_ids

    first, second = await asyncio.gather(run(session, "s-a"), run(other, "s-b"))
    assert first == ("s-a",)
    assert second == ("s-b",)
    assert session.declared_step_ids == ("s-a",)
    assert other.declared_step_ids == ("s-b",)
    assert session.snapshot().scope.matches(SCOPE_A)
    assert other.snapshot().scope.matches(SCOPE_B)


async def test_child_publish() -> None:
    """Required aggregate case: child declarations publish through the session."""
    active = TurnTaskSession(SCOPE_A, turn_id="turn-1", task_id="t-1", plan_revision=3)
    await test_child_publish_declaration_reaches_later_siblings(active)

    active = TurnTaskSession(SCOPE_A, turn_id="turn-1", task_id="t-1")
    await test_child_publish_rebinding_the_contextvar_does_not_publish(active)

    active = TurnTaskSession(SCOPE_A, turn_id="turn-1", task_id="t-1")
    await test_child_publish_from_thread_work(active)

    active = TurnTaskSession(SCOPE_A, turn_id="turn-1", task_id="t-1")
    await test_child_publish_survives_many_concurrent_declarers(active)


# ─────────────────────────────────────────────────────────────
# Attribution
# ─────────────────────────────────────────────────────────────


async def test_attribution_zero_one_many(session: TurnTaskSession) -> None:
    """Zero declarations give none, one gives declared, two give ambiguous."""
    assert session.snapshot().attribution is Attribution.NONE
    assert session.snapshot().attributed_step_id is None

    session.declare("s-clean")
    one = session.snapshot()
    assert one.attribution is Attribution.DECLARED
    assert one.attributed_step_id == "s-clean"

    session.declare("s-report")
    many = session.snapshot()
    assert many.attribution is Attribution.AMBIGUOUS
    assert many.attributed_step_id is None, "ambiguous is task-level; never guess one of the two"


async def test_attribution_prior_snapshots_never_change(session: TurnTaskSession) -> None:
    """A later declaration does not retroactively revise an earlier snapshot."""
    session.declare("s-clean")
    first = session.snapshot()
    assert first.attribution is Attribution.DECLARED

    session.declare("s-report")
    second = session.snapshot()

    assert first.declared_step_ids == ("s-clean",), "the earlier snapshot is frozen"
    assert first.attribution is Attribution.DECLARED
    assert second.attribution is Attribution.AMBIGUOUS

    # And the same holds for a receipt captured before the second declaration.
    with turn_session(SCOPE_A, session=session):
        pass
    assert first.model_dump() != second.model_dump()


async def test_attribution_dispatch_before_a_later_declaration_keeps_its_snapshot(
    session: TurnTaskSession,
) -> None:
    """An in-flight dispatch keeps the attribution it had at dispatch time."""
    session.declare("s-clean")

    with turn_session(SCOPE_A, session=session):
        with session.invocation("wm_store") as early:
            # A second declaration arrives while the call is in flight.
            session.declare("s-report")
            session.complete_invocation(early, outcome=CallOutcome.SUCCESS, executed=True)

        with session.invocation("wm_store") as late:
            session.complete_invocation(late, outcome=CallOutcome.SUCCESS, executed=True)

    assert early.context.attribution is Attribution.DECLARED
    assert early.context.attributed_step_id == "s-clean"
    assert late.context.attribution is Attribution.AMBIGUOUS
    assert late.context.attributed_step_id is None


async def test_attribution_explicit_plan_mapping_overrides(session: TurnTaskSession) -> None:
    """An explicit plan-to-step mapping wins over the declaration count."""
    session.declare("s-clean")
    session.declare("s-report")

    mapped = session.snapshot(plan_node_id="node-3", mapped_step_id="s-report")
    assert mapped.attribution is Attribution.PLAN
    assert mapped.attributed_step_id == "s-report"


async def test_attribution_unmapped_plan_node_stays_task_level(session: TurnTaskSession) -> None:
    """A plan node id is not a step id; an unmapped plan call stays task-level."""
    session.declare("s-clean")
    unmapped = session.snapshot(plan_run_id="run-1", plan_node_id="node-3", plan_item_index=2, plan_attempt=1)

    assert unmapped.attribution is Attribution.PLAN
    assert unmapped.attributed_step_id is None, "never promote a plan node id to a domain step id"
    assert (unmapped.plan_run_id, unmapped.plan_node_id, unmapped.plan_item_index) == ("run-1", "node-3", 2)


async def test_attribution_snapshot_carries_selection_and_revision(session: TurnTaskSession) -> None:
    """Snapshots carry the selected task and plan revision at dispatch time."""
    first = session.snapshot()
    assert (first.task_id, first.plan_revision, first.turn_id) == ("t-1", 3, "turn-1")

    session.select_task("t-2")
    session.set_plan_revision(4)
    second = session.snapshot()
    assert (second.task_id, second.plan_revision) == ("t-2", 4)
    assert (first.task_id, first.plan_revision) == ("t-1", 3), "the earlier snapshot is frozen"

    with pytest.raises(ValueError):
        session.set_plan_revision(-1)


async def test_attribution_declaration_scope_withdraws_on_error(session: TurnTaskSession) -> None:
    """A scoped declaration is withdrawn even when the block raises."""
    with pytest.raises(RuntimeError):
        with session.declaration("s-clean"):
            assert session.declared_step_ids == ("s-clean",)
            raise RuntimeError("boom")
    assert session.declared_step_ids == (), "a failed step must not leave the turn ambiguous"


async def test_attribution_barrier_waits_for_in_flight_work(session: TurnTaskSession) -> None:
    """The explicit completion barrier is how ambiguity is avoided, not guessing."""
    release = asyncio.Event()
    observed: list = []

    async def slow_call() -> None:
        with session.invocation("slow_tool") as receipt:
            await release.wait()
            session.complete_invocation(receipt, outcome=CallOutcome.SUCCESS, executed=True)

    with turn_session(SCOPE_A, session=session):
        session.declare("s-clean")
        task = spawn_task(slow_call())
        await asyncio.sleep(0)
        assert session.open_call_ids, "the call is in flight"

        async def after_barrier() -> None:
            await session.barrier()
            observed.append(tuple(session.open_call_ids))

        waiter = spawn_task(after_barrier())
        await asyncio.sleep(0)
        assert not observed, "the barrier must not resolve while work is in flight"

        release.set()
        await task
        await waiter

    assert observed == [()], "the barrier resolves only once the turn is quiescent"

    # A barrier with nothing in flight resolves immediately.
    await session.barrier()


async def test_attribution() -> None:
    """Required aggregate case: attribution is decided at dispatch and never revised."""
    active = TurnTaskSession(SCOPE_A, turn_id="turn-1", task_id="t-1", plan_revision=3)
    await test_attribution_zero_one_many(active)

    active = TurnTaskSession(SCOPE_A, turn_id="turn-1", task_id="t-1", plan_revision=3)
    await test_attribution_prior_snapshots_never_change(active)

    active = TurnTaskSession(SCOPE_A, turn_id="turn-1", task_id="t-1", plan_revision=3)
    await test_attribution_dispatch_before_a_later_declaration_keeps_its_snapshot(active)

    active = TurnTaskSession(SCOPE_A, turn_id="turn-1", task_id="t-1", plan_revision=3)
    await test_attribution_explicit_plan_mapping_overrides(active)

    active = TurnTaskSession(SCOPE_A, turn_id="turn-1", task_id="t-1", plan_revision=3)
    await test_attribution_unmapped_plan_node_stays_task_level(active)


# ─────────────────────────────────────────────────────────────
# Lifecycle and reset
# ─────────────────────────────────────────────────────────────


async def test_reset_binding_is_released_on_success() -> None:
    """A clean turn releases TASK_CONTEXT."""
    assert current_session() is None
    with turn_session(SCOPE_A, turn_id="turn-1") as active:
        assert current_session() is active
    assert current_session() is None


async def test_reset_binding_is_released_on_exception() -> None:
    """An exception mid-turn still releases TASK_CONTEXT."""
    with pytest.raises(RuntimeError):
        with turn_session(SCOPE_A, turn_id="turn-1"):
            assert current_session() is not None
            raise RuntimeError("boom")
    assert current_session() is None, "scope must not leak past a failed turn"


async def test_reset_binding_is_released_on_cancellation() -> None:
    """A cancelled turn releases TASK_CONTEXT during finalization."""
    entered = asyncio.Event()

    async def cancellable() -> None:
        with turn_session(SCOPE_A, turn_id="turn-1"):
            entered.set()
            await asyncio.sleep(3600)

    task = spawn_task(cancellable())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert current_session() is None


async def test_reset_streaming_generator_release_on_aclose() -> None:
    """A cancelled/abandoned stream still runs the finally that resets scope."""
    seen: list = []

    async def stream():
        with turn_session(SCOPE_A, turn_id="turn-stream") as active:
            seen.append(active)
            yield 1
            yield 2

    generator = stream()
    assert await generator.__anext__() == 1
    await generator.aclose()  # abandon mid-stream

    assert seen, "the stream did bind a session"
    assert current_session() is None, "an abandoned stream must not leak scope"


async def test_reset_async_context_manager_form() -> None:
    """``async with`` binds and releases identically."""
    async with async_turn_session(SCOPE_A, turn_id="turn-1") as active:
        assert current_session() is active
    assert current_session() is None

    with pytest.raises(RuntimeError):
        async with async_turn_session(SCOPE_A, turn_id="turn-1"):
            raise RuntimeError("boom")
    assert current_session() is None


async def test_reset_nested_turns_restore_the_outer_session() -> None:
    """Nesting restores the outer session, it does not clear it."""
    outer = TurnTaskSession(SCOPE_A, turn_id="outer")
    inner = TurnTaskSession(SCOPE_A, turn_id="inner")

    with turn_session(SCOPE_A, session=outer):
        with turn_session(SCOPE_A, session=inner):
            assert current_session() is inner
        assert current_session() is outer, "the outer turn survives the inner one"
    assert current_session() is None


async def test_reset_current_call_is_released_on_exception(session: TurnTaskSession) -> None:
    """A failing dispatch resets CURRENT_CALL and records a truthful outcome."""
    with turn_session(SCOPE_A, session=session):
        assert current_call_id() is None
        with pytest.raises(RuntimeError):
            with session.invocation("wm_store") as receipt:
                assert current_call_id() == receipt.call_id
                raise RuntimeError("tool exploded")
        assert current_call_id() is None

    assert receipt.outcome is CallOutcome.UNKNOWN, "an unexplained exception is unknown, not success"
    assert receipt.terminal_event_type is EventType.TOOL_OUTCOME_UNKNOWN
    assert session.open_call_ids == ()


async def test_reset_cancellation_records_and_reraises(session: TurnTaskSession) -> None:
    """Cancellation is recorded (bounded) and then propagates unchanged."""
    entered = asyncio.Event()
    receipts: list = []

    async def cancellable() -> None:
        with turn_session(SCOPE_A, session=session):
            with session.invocation("slow_tool") as receipt:
                receipts.append(receipt)
                entered.set()
                await asyncio.sleep(3600)

    task = spawn_task(cancellable())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    receipt = receipts[0]
    assert receipt.outcome is CallOutcome.CANCELLED
    assert receipt.terminal_event_type is EventType.TOOL_CANCELLED
    assert not receipt.outcome.is_resolved, "cancelled stays unresolved until an explicit later attempt"
    assert current_call_id() is None
    assert session.open_call_ids == ()


async def test_reset_nested_invocations_carry_parent_and_restore(session: TurnTaskSession) -> None:
    """A nested dispatch records its parent and restores it on exit."""
    with turn_session(SCOPE_A, session=session):
        with session.invocation("plan_node") as parent:
            assert current_call_id() == parent.call_id
            with session.invocation("child_tool") as child:
                assert current_call_id() == child.call_id
                assert child.parent_call_id == parent.call_id
                assert child.context.parent_call_id == parent.call_id
                session.complete_invocation(child, outcome=CallOutcome.SUCCESS, executed=True)
            assert current_call_id() == parent.call_id, "the parent is restored, not cleared"
            session.complete_invocation(parent, outcome=CallOutcome.SUCCESS, executed=True)

    assert parent.parent_call_id is None


async def test_reset_parent_aggregate_is_not_a_second_child_execution(session: TurnTaskSession) -> None:
    """Retries are separate attempts; the parent aggregate is not one of them."""
    with turn_session(SCOPE_A, session=session):
        with session.invocation("plan_node", plan_run_id="run-1", plan_node_id="node-1") as parent:
            for attempt in (1, 2):
                with session.invocation("flaky_tool", attempt=attempt) as child:
                    session.complete_invocation(
                        child,
                        outcome=CallOutcome.ERROR if attempt == 1 else CallOutcome.SUCCESS,
                        executed=True,
                    )
            session.complete_invocation(parent, outcome=CallOutcome.SUCCESS, executed=True)

    children = [r for r in session.records if r.tool_name == "flaky_tool"]
    assert [r.attempt for r in children] == [1, 2], "each physical attempt is counted once"
    assert len({r.call_id for r in children}) == 2, "attempts have distinct call ids"
    assert all(r.parent_call_id == parent.call_id for r in children)

    aggregates = [r for r in session.records if r.tool_name == "plan_node"]
    assert len(aggregates) == 1
    assert aggregates[0].parent_call_id is None, "the aggregate is distinguishable from its children"


async def test_reset_early_dispatch_returns_are_not_executed(session: TurnTaskSession) -> None:
    """An unknown tool or a guard denial never claims a tool body ran."""
    with turn_session(SCOPE_A, session=session):
        with session.invocation("missing_tool") as unknown:
            session.complete_invocation(
                unknown, outcome=CallOutcome.NOT_EXECUTED, executed=False, error="Tool not found"
            )
        with session.invocation("guarded_tool") as denied:
            session.complete_invocation(denied, outcome=CallOutcome.DENIED, executed=False, error="Policy denied")

    assert unknown.executed is False and denied.executed is False
    assert unknown.terminal_event_type is EventType.TOOL_FAILED
    assert denied.terminal_event_type is EventType.TOOL_FAILED


async def test_reset_records_are_captured_once(session: TurnTaskSession) -> None:
    """The turn captures one canonical record per attempt, in start order."""
    with turn_session(SCOPE_A, session=session):
        for name in ("a", "b", "c"):
            with session.invocation(name) as receipt:
                session.complete_invocation(receipt, outcome=CallOutcome.SUCCESS, executed=True)

    assert [r.tool_name for r in session.records] == ["a", "b", "c"]
    assert len({r.call_id for r in session.records}) == 3
    for record in session.records:
        assert session.receipt(record.call_id) is record
    assert session.receipt("no-such-call") is None


async def test_reset_plan_receipt_survives_post_dispatch_store(session: TurnTaskSession) -> None:
    """A plan node's post-dispatch _store still attributes its artifact.

    Mirrors ``bots/flows/plan/node.py``: ``_store`` (:347) runs after
    ``_call_with_retry`` (:414) has returned and the dispatcher has reset
    its per-invocation context.
    """
    with turn_session(SCOPE_A, session=session):
        # _call_with_retry: dispatch happens and completes.
        with session.invocation("fetch_prices", plan_run_id="run-1", plan_node_id="node-1") as attempt:
            session.complete_invocation(attempt, outcome=CallOutcome.SUCCESS, executed=True)

        # Dispatcher context is gone by now — this is the hazard.
        assert current_call_id() is None
        assert producer_call_id() is None, "without retention the provenance is honestly None"

        # _store: the node retains the receipt across the boundary.
        with session.retained_producer(attempt.call_id):
            assert producer_call_id() == attempt.call_id
            ref = EvidenceRef(artifact_id="art-1", version=1)
            assert session.add_artifact_receipt(producer_call_id(), ref) is True

        assert producer_call_id() is None, "retention is scoped, not sticky"

    assert attempt.artifact_receipts == (EvidenceRef(artifact_id="art-1", version=1),)
    assert session.add_artifact_receipt("unknown-call", EvidenceRef(artifact_id="x", version=1)) is False


async def test_reset_retained_producer_beats_ambient_call(session: TurnTaskSession) -> None:
    """An explicit retained producer wins over the ambient current call."""
    with turn_session(SCOPE_A, session=session):
        with session.invocation("outer") as outer:
            with session.retained_producer("explicit-call-id"):
                assert current_call_id() == outer.call_id
                assert producer_call_id() == "explicit-call-id"
            assert producer_call_id() == outer.call_id
            session.complete_invocation(outer, outcome=CallOutcome.SUCCESS, executed=True)


async def test_reset_artifact_receipts_are_deduplicated(session: TurnTaskSession) -> None:
    """Attaching the same artifact version twice does not duplicate it."""
    with turn_session(SCOPE_A, session=session):
        with session.invocation("tool") as receipt:
            session.complete_invocation(receipt, outcome=CallOutcome.SUCCESS, executed=True)
    ref = EvidenceRef(artifact_id="art-1", version=1)
    assert session.add_artifact_receipt(receipt.call_id, ref) is True
    assert session.add_artifact_receipt(receipt.call_id, ref) is True
    assert receipt.artifact_receipts == (ref,)


async def test_reset() -> None:
    """Required aggregate case: every exit path resets the ContextVars."""
    await test_reset_binding_is_released_on_success()
    await test_reset_binding_is_released_on_exception()
    await test_reset_binding_is_released_on_cancellation()
    await test_reset_streaming_generator_release_on_aclose()
    await test_reset_async_context_manager_form()
    await test_reset_nested_turns_restore_the_outer_session()

    active = TurnTaskSession(SCOPE_A, turn_id="turn-1", task_id="t-1")
    await test_reset_current_call_is_released_on_exception(active)

    active = TurnTaskSession(SCOPE_A, turn_id="turn-1", task_id="t-1")
    await test_reset_cancellation_records_and_reraises(active)

    active = TurnTaskSession(SCOPE_A, turn_id="turn-1", task_id="t-1")
    await test_reset_nested_invocations_carry_parent_and_restore(active)


# ─────────────────────────────────────────────────────────────
# Envelope across the process boundary
# ─────────────────────────────────────────────────────────────


async def test_envelope_is_bounded_and_carries_no_payload(session: TurnTaskSession) -> None:
    """Only the bounded context crosses a process boundary."""
    session.declare("s-clean")
    with turn_session(SCOPE_A, session=session):
        with session.invocation("repl") as receipt:
            envelope = session.envelope(worker_session_id="w-1", worker_generation=2, fencing_token=7)
            session.complete_invocation(receipt, outcome=CallOutcome.SUCCESS, executed=True)

    dumped = envelope.model_dump()
    assert set(dumped) == {
        "scope",
        "task_id",
        "turn_id",
        "plan_revision",
        "call_id",
        "declared_step_ids",
        "worker_session_id",
        "worker_generation",
        "fencing_token",
    }
    assert envelope.call_id == receipt.call_id
    assert envelope.declared_step_ids == ("s-clean",)
    assert TurnContextEnvelope.model_validate_json(envelope.model_dump_json()) == envelope

    with pytest.raises(ValidationError):
        envelope.task_id = "t-9"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        TurnContextEnvelope(scope=SCOPE_A, payload={"rows": []})  # type: ignore[call-arg]


async def test_envelope_revalidates_scope(session: TurnTaskSession) -> None:
    """A returning envelope from another scope is a cross-user read."""
    envelope = session.envelope()
    foreign = TurnTaskSession(SCOPE_B, turn_id="turn-b", task_id="t-1")
    with pytest.raises(ScopeViolation):
        envelope.revalidate(foreign)


async def test_envelope_revalidates_selection_and_generation(session: TurnTaskSession) -> None:
    """Selection, worker generation and fencing token are all rechecked."""
    envelope = session.envelope(worker_session_id="w-1", worker_generation=2, fencing_token=7)
    envelope.revalidate(session, worker_session_id="w-1", worker_generation=2, fencing_token=7)

    with pytest.raises(StaleTurnContext, match="worker generation identity"):
        envelope.revalidate(session, worker_session_id="w-2")
    with pytest.raises(StaleTurnContext, match="worker generation changed"):
        envelope.revalidate(session, worker_generation=3)
    with pytest.raises(StaleTurnContext, match="fencing token"):
        envelope.revalidate(session, fencing_token=8)

    session.select_task("t-9")
    with pytest.raises(StaleTurnContext, match="selected task changed"):
        envelope.revalidate(session)


async def test_session_repr_leaks_nothing(session: TurnTaskSession) -> None:
    """The debug representation never includes payloads or declarations."""
    session.declare("s-secret-step-name")
    text = repr(session)
    assert "turn-1" in text and "t-1" in text
    assert "s-secret-step-name" not in text, "counts, not contents"
