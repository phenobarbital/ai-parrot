"""Required checkpoint barrier in the explicit-mode scheduler (TASK-2624).

``AgentsFlow(checkpoint_required=True)`` turns the awaited
``FlowCheckpointer.checkpoint()`` (TASK-2623) into a genuine execution
barrier: after a node succeeds (``ctx.mark_completed()``) and after any
back-edge retry-reset is computed and applied to both scheduler state and
``ctx`` (``FlowContext.reset_completed()``), the scheduler awaits the
checkpoint write and only then dispatches whatever this event made
eligible — a normal downstream target, a skip cascade, or a repair-loop
re-entry. A ``CheckpointPersistenceError`` (including a lost resume lease)
fails the run outright: no new work dispatches, and already-active sibling
tasks are cancelled.

Default (``checkpoint_required=False``, including plain ``checkpoint=True``)
keeps the historical best-effort ``make_listener()`` behavior unchanged —
covered here by re-running TASK-2623's
``test_best_effort_checkpoint_behavior_unchanged`` scenario end-to-end
through the scheduler once more, plus a dedicated check that required mode
does NOT attach the fire-and-forget listener at all.
"""
import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest
from parrot.bots.flows.core.checkpoint import CheckpointPersistenceError
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.fsm import AgentTaskMachine
from parrot.bots.flows.core.node import Node
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition
from parrot.bots.flows.flow.flow import AgentsFlow, register_node
from pydantic import Field

from .test_suspend_resume import FakeCheckpointStore


@register_node("required-barrier.step")
class _StepNode(Node):
    """A node that appends to a shared sink and returns a labeled result."""

    dependencies: set[str] = Field(default_factory=set)
    successors: set[str] = Field(default_factory=set)
    fsm: AgentTaskMachine | None = None
    sink: Any = None
    label: str = ""

    def model_post_init(self, _context: Any) -> None:
        if self.fsm is None:
            object.__setattr__(self, "fsm", AgentTaskMachine(agent_name=self.node_id))

    @property
    def name(self) -> str:
        return self.node_id

    async def execute(self, ctx: FlowContext, deps: Any, **kwargs: Any) -> dict:
        if self.sink is not None:
            self.sink.append(self.node_id)
        ctx.shared_data.setdefault("order", []).append(self.node_id)
        return {"status": self.label or "ok"}


def _linear_flow(sink: list, *, flow_id: str, store, required: bool) -> AgentsFlow:
    """a -> b, a trivial two-node explicit-edge graph."""
    flow = AgentsFlow(
        name="required-barrier",
        flow_id=flow_id,
        checkpoint=True,
        checkpoint_store=store,
        checkpoint_required=required,
    )
    flow.add_node(_StepNode(node_id="a", sink=sink))
    flow.add_node(_StepNode(node_id="b", sink=sink))
    flow.add_edge("a", "b", condition="on_success")
    return flow


@pytest.fixture
def fake_store() -> FakeCheckpointStore:
    return FakeCheckpointStore()


# ---------------------------------------------------------------------------
# Barrier ordering: downstream must not start before put() lands
# ---------------------------------------------------------------------------


async def test_required_checkpoint_awaits_put_before_routing(fake_store) -> None:
    """Block put() with an event; assert downstream node has not started."""
    put_blocked = asyncio.Event()
    put_may_proceed = asyncio.Event()
    real_put = fake_store.put

    async def _blocking_put(checkpoint):
        put_blocked.set()
        await put_may_proceed.wait()
        await real_put(checkpoint)

    fake_store.put = _blocking_put

    sink: list = []
    flow = _linear_flow(sink, flow_id="barrier-1", store=fake_store, required=True)

    run_task = asyncio.create_task(flow.run_flow(FlowContext(initial_task="t")))

    await asyncio.wait_for(put_blocked.wait(), timeout=2.0)
    # 'a' has run (it triggered the checkpoint write), but 'b' must NOT have
    # started yet — the required barrier is still awaiting put().
    assert sink == ["a"]

    put_may_proceed.set()
    result = await asyncio.wait_for(run_task, timeout=2.0)

    assert result.status.value == "completed"
    assert sink == ["a", "b"]


# ---------------------------------------------------------------------------
# Failure containment
# ---------------------------------------------------------------------------


async def test_required_checkpoint_put_failure_raises(fake_store) -> None:
    """ConnectionError in put() -> CheckpointPersistenceError; dispatch count == 0."""
    fake_store.put = AsyncMock(side_effect=ConnectionError("redis unavailable"))

    sink: list = []
    flow = _linear_flow(sink, flow_id="barrier-2", store=fake_store, required=True)

    with pytest.raises(CheckpointPersistenceError):
        await flow.run_flow(FlowContext(initial_task="t"))

    # 'a' ran (that is what triggered the failed checkpoint); 'b' never did.
    assert sink == ["a"]


async def test_required_checkpoint_failure_cancels_active_siblings(fake_store) -> None:
    """A slow sibling still in flight when the barrier fails must be cancelled."""
    fake_store.put = AsyncMock(side_effect=ConnectionError("redis unavailable"))

    sink: list = []
    cancelled = {"slow": False}

    class _SlowNode(_StepNode):
        async def execute(self, ctx: FlowContext, deps: Any, **kwargs: Any) -> dict:
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                cancelled["slow"] = True
                raise
            return {"status": "ok"}

    flow = AgentsFlow(
        name="required-barrier-fanout",
        flow_id="barrier-3",
        checkpoint=True,
        checkpoint_store=fake_store,
        checkpoint_required=True,
    )
    flow.add_node(_StepNode(node_id="a", sink=sink))
    flow.add_node(_SlowNode(node_id="slow", sink=sink))
    flow.add_node(_StepNode(node_id="c", sink=sink))
    # Both 'a' and 'slow' are entry nodes (no incoming edges) — dispatched
    # together at the start. 'a' completes fast and hits the failing
    # checkpoint barrier while 'slow' is still in flight.
    flow.add_edge("a", "c", condition="on_success")

    with pytest.raises(CheckpointPersistenceError):
        await flow.run_flow(FlowContext(initial_task="t"))

    assert cancelled["slow"] is True
    assert "c" not in sink


# ---------------------------------------------------------------------------
# Retry-frontier persistence — a crash after a repair back-edge
# ---------------------------------------------------------------------------


class _StubRegistry:
    """No agent-typed nodes in these graphs; the registry is a formality."""

    def get_bot_instance(self, name: str) -> object:
        return None


def _repair_loop_flow(*, flow_id: str | None, store, dev_runs: list, qa_runs: list) -> AgentsFlow:
    """dev -> qa; qa retries dev while attempt < 2, else routes to end.

    The attempt counter lives in ``ctx.shared_data`` (not a Python closure)
    so it behaves exactly like the real dev-loop repair loop: it SURVIVES
    ``FlowContext.reset_completed()`` (which only clears completed_tasks/
    results/responses/node_metadata/errors, never shared_data), so a
    checkpoint taken right after the reset still remembers "attempt 1
    already happened" and a resumed run continues the SAME bounded retry
    instead of restarting the whole 2-round cycle from scratch.
    """

    class _DevNode(_StepNode):
        async def execute(self, ctx: FlowContext, deps: Any, **kwargs: Any) -> dict:
            dev_runs.append(self.node_id)
            return {"status": "ok"}

    class _QaNode(_StepNode):
        async def execute(self, ctx: FlowContext, deps: Any, **kwargs: Any) -> dict:
            n = ctx.shared_data.get("qa_attempt", 0) + 1
            ctx.shared_data["qa_attempt"] = n
            qa_runs.append(n)
            return {"attempt": n}

    # Callable (non-CEL-string) predicates cannot round-trip through
    # to_definition() — supply an external checkpoint_definition (TASK-2623)
    # so _ensure_checkpointer() skips it entirely, matching how a real
    # dev-loop/dev-flow builder wires this (spec §3 Module 2/3).
    external_definition = FlowDefinition(
        flow="repair-loop",
        nodes=[
            NodeDefinition(id="dev", type="required-barrier.step"),
            NodeDefinition(id="qa", type="required-barrier.step"),
            NodeDefinition(id="end", type="required-barrier.step"),
        ],
        edges=[],
    )
    kwargs: dict[str, Any] = {
        "name": "repair-loop",
        "checkpoint": True,
        "checkpoint_store": store,
        "checkpoint_required": True,
        "checkpoint_definition": external_definition,
    }
    if flow_id is not None:
        kwargs["flow_id"] = flow_id
    flow = AgentsFlow(**kwargs)
    flow.add_node(_DevNode(node_id="dev"))
    flow.add_node(_QaNode(node_id="qa"))
    flow.add_node(_StepNode(node_id="end"))
    flow.add_edge("dev", "qa", condition="on_success")
    flow.add_edge("qa", "end", condition="on_condition", predicate=lambda r: r["attempt"] >= 2)
    flow.add_edge("qa", "dev", condition="on_condition", predicate=lambda r: r["attempt"] < 2)
    return flow


async def test_retry_checkpoint_restores_post_reset_frontier(fake_store) -> None:
    """QA-fail back-edge fires; process 'crashes'; resume reruns the repair
    cycle instead of skipping it (reset members absent from completed set)."""
    dev_runs: list = []
    qa_runs: list = []
    flow = _repair_loop_flow(flow_id="repair-1", store=fake_store, dev_runs=dev_runs, qa_runs=qa_runs)
    result = await flow.run_flow(FlowContext(initial_task="t"))
    assert result.status.value == "completed"
    assert dev_runs == ["dev", "dev"]
    assert qa_runs == [1, 2]

    # The checkpoint written right after qa's FIRST completion (attempt=1)
    # triggers the back-edge reset: both 'dev' and 'qa' leave completed_tasks
    # in that checkpoint's context (spec §2/§7 "retry-safe snapshot") —
    # BEFORE 'dev' is re-dispatched for the retry pass. shared_data (the
    # attempt counter) is untouched by the reset.
    history = await fake_store.history("repair-1", limit=20)
    post_reset_checkpoint = next(
        cp
        for cp in reversed(history)  # earliest-first
        if "dev" not in cp.context.completed_tasks and "qa" not in cp.context.completed_tasks and cp.checkpoint_id > 1
    )
    assert "dev" not in post_reset_checkpoint.context.completed_tasks
    assert "qa" not in post_reset_checkpoint.context.completed_tasks
    assert post_reset_checkpoint.context.shared_data.get("qa_attempt") == 1

    # "Crash" and resume from exactly that checkpoint in a fresh process.
    replay_dev: list = []
    replay_qa: list = []
    resumed = await AgentsFlow.resume(
        "repair-1",
        post_reset_checkpoint.checkpoint_id,
        agent_registry=_StubRegistry(),
        store=fake_store,
        flow_factory=lambda _definition: _repair_loop_flow(
            flow_id=None, store=fake_store, dev_runs=replay_dev, qa_runs=replay_qa
        ),
    )
    await resumed.run_flow()

    # 'dev' and 'qa' each rerun exactly once — the reset frontier is
    # genuinely re-executed (not skipped as already-complete), and the
    # surviving shared_data attempt counter (1) means this single replay
    # pass is attempt 2, which satisfies the predicate and reaches 'end'
    # directly — the resumed run continues the SAME bounded retry instead
    # of restarting the whole 2-round cycle from scratch.
    assert replay_dev == ["dev"]
    assert replay_qa == [2]


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


async def test_best_effort_checkpoint_behavior_unchanged(fake_store) -> None:
    """Default (checkpoint_required=False) still swallows listener write failures."""
    fake_store.put = AsyncMock(side_effect=ConnectionError("redis unavailable"))

    sink: list = []
    flow = _linear_flow(sink, flow_id="best-effort-barrier", store=fake_store, required=False)

    result = await flow.run_flow(FlowContext(initial_task="t"))

    assert result.status.value == "completed"
    assert sink == ["a", "b"]


# ---------------------------------------------------------------------------
# Lease-heartbeat loss surfaces as a hard failure (spec §7)
# ---------------------------------------------------------------------------


async def test_lease_heartbeat_loss_surfaces_as_persistence_error(fake_store) -> None:
    """A renew_lease() that returns False sets lease_lost and fails checkpoint()."""
    from parrot.bots.flows.core.checkpoint import FlowCheckpointer

    fake_store.renew_lease = AsyncMock(return_value=False)

    checkpointer = FlowCheckpointer(
        flow_id="heartbeat-1",
        flow_name="heartbeat-flow",
        definition=FlowDefinition(flow="heartbeat-flow", nodes=[], edges=[]),
        store=fake_store,
    )
    await checkpointer.acquire_lease("holder-1", ttl=1)
    assert checkpointer.lease_lost is False

    # interval = max(ttl/3, 1) == 1s; give the background heartbeat task one
    # full cycle to observe the failed renewal.
    await asyncio.sleep(1.3)

    assert checkpointer.lease_lost is True
    with pytest.raises(CheckpointPersistenceError):
        checkpointer.raise_if_lease_lost()
    with pytest.raises(CheckpointPersistenceError):
        await checkpointer.checkpoint(FlowContext(initial_task="t"))

    await checkpointer.release_lease()


async def test_lease_heartbeat_loss_fails_the_active_required_job(fake_store) -> None:
    """The scheduler barrier itself refuses to dispatch once the lease is lost."""
    sink: list = []
    flow = _linear_flow(sink, flow_id="heartbeat-2", store=fake_store, required=True)
    ctx = FlowContext(initial_task="t")

    # Drive the same two steps run_flow() performs, so the lease can be
    # flipped "lost" between them without waiting a real heartbeat interval.
    checkpointer, _listener = await flow._ensure_checkpointer(ctx)
    assert checkpointer is not None
    checkpointer._lease_lost = True  # simulate a heartbeat-detected loss

    with pytest.raises(CheckpointPersistenceError):
        await flow._run_flow_scheduler(ctx)

    # 'a' ran (the barrier fires right after it), but 'b' never started.
    assert sink == ["a"]
    await checkpointer.aclose()


async def test_required_mode_does_not_attach_fire_and_forget_listener(fake_store) -> None:
    """spec §7: 'required persistence must not run through make_listener()'."""
    sink: list = []
    flow = _linear_flow(sink, flow_id="no-listener-flow", store=fake_store, required=True)

    await flow.run_flow(FlowContext(initial_task="t"))

    assert flow._node_event_listeners == []


async def test_non_required_mode_still_attaches_listener(fake_store) -> None:
    """checkpoint_required=False (default) keeps the historical listener wiring."""
    sink: list = []
    flow = _linear_flow(sink, flow_id="listener-flow", store=fake_store, required=False)

    await flow.run_flow(FlowContext(initial_task="t"))

    # The listener is removed again in run_flow()'s finally block, but the
    # checkpoints it wrote along the way prove it fired.
    history = await fake_store.history("listener-flow", limit=20)
    assert len(history) >= 2
