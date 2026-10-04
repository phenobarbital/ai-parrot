"""FEAT-585 M4 PlanFlow checkpoint lifecycle coverage."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

from parrot.bots.flows.core.checkpoint import CheckpointPersistenceError
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.plan import ExecutionPlan, PlanNode
from parrot.tools.execution_plan.checkpoint import PlanFlow, build_plan_flow, plan_run_projector
from parrot.tools.execution_plan.models import PLAN_RUN_SHARED_KEY, PlanRunMetadata
from parrot.tools.execution_plan.runs import plan_fingerprint, process_identity
from parrot.tools.working_memory.tool import WorkingMemoryToolkit

from ._recovery_fakes import CountingToolManager, SerializingFakeCheckpointStore

pytestmark = pytest.mark.asyncio


class _Registry:
    """Registry double; tool-only plans never resolve an agent."""

    def get_bot_instance(self, name: str) -> None:
        """Return no agent because this flow has only tool nodes."""
        return None


def _plan() -> ExecutionPlan:
    """Build a single-node checkpointed execution plan."""
    return ExecutionPlan(
        name="checkpoint-plan",
        objective="verify checkpoint boundaries",
        nodes=[PlanNode(id="step", tool="tool", store_as="step_out")],
    )


def _metadata(plan: ExecutionPlan, run_id: str = "checkpoint-run") -> PlanRunMetadata:
    """Build the required plan-run checkpoint envelope."""
    return PlanRunMetadata(
        run_id=run_id,
        root_run_id=run_id,
        parent_run_id=None,
        plan=plan,
        original_plan=plan,
        source="plan_name",
        started_at=datetime.now(timezone.utc),
        allowed_tools=["tool"],
        plan_fingerprint=plan_fingerprint(plan),
        artifact_mode="memory",
        process_id=process_identity(),
    )


def _flow(
    store: SerializingFakeCheckpointStore,
    manager: CountingToolManager,
    *,
    run_id: str = "checkpoint-run",
) -> PlanFlow:
    """Build a fully bound PlanFlow used by lifecycle tests."""
    plan = _plan()
    return build_plan_flow(
        plan,
        run=_metadata(plan, run_id),
        tool_manager=manager,
        working_memory=WorkingMemoryToolkit(),
        agent_registry=_Registry(),  # type: ignore[arg-type]
        permission_context=None,
        step_mapping={},
        store=store,
        durable_store=None,
    )


def _context(plan: ExecutionPlan) -> FlowContext:
    """Build a context containing a JSON-safe plan-run envelope."""
    ctx = FlowContext(initial_task=plan.objective)
    ctx.shared_data[PLAN_RUN_SHARED_KEY] = _metadata(plan).model_dump(mode="json")
    return ctx


def test_fresh_flow_forces_required_and_projector() -> None:
    """Checkpointed PlanFlow instances force required plan-only persistence."""
    flow = PlanFlow("fresh", checkpoint=True)

    assert flow._checkpoint_required is True
    assert flow._checkpoint_shared_data_arg is plan_run_projector
    assert flow._checkpoint_include_responses is False


def test_disabled_flow_is_plain() -> None:
    """Disabled checkpoints preserve the ordinary AgentsFlow defaults."""
    flow = PlanFlow("plain", checkpoint=False)

    assert flow._checkpoint_required is False
    assert flow._checkpoint_shared_data_arg is None


async def test_resumed_flow_keeps_options() -> None:
    """A factory-rebuilt PlanFlow retains its forced checkpoint policy."""
    store = SerializingFakeCheckpointStore()
    manager = CountingToolManager({"tool": {"ok": True}})
    flow = _flow(store, manager)
    await flow.run_flow(_context(_plan()))

    resumed = await PlanFlow.resume(
        "checkpoint-run",
        agent_registry=_Registry(),  # type: ignore[arg-type]
        store=store,
        flow_factory=lambda _definition: _flow(store, manager),
    )

    assert isinstance(resumed, PlanFlow)
    assert resumed._checkpoint_required is True
    assert resumed._checkpoint_shared_data_arg is plan_run_projector
    await resumed._checkpointer.aclose()  # type: ignore[union-attr]


async def test_initial_and_terminal_records() -> None:
    """Start and terminal records contain the envelope but never responses."""
    store = SerializingFakeCheckpointStore()
    manager = CountingToolManager({"tool": {"ok": True}})
    flow = _flow(store, manager)
    ctx = _context(_plan())
    envelope = ctx.shared_data[PLAN_RUN_SHARED_KEY]
    await flow.run_flow(ctx)

    first = await store.get("checkpoint-run", 1)
    latest = await store.latest("checkpoint-run")
    assert first is not None
    assert latest is not None
    assert first.status == "running"
    assert first.context.results == {}
    assert first.context.shared_data == {PLAN_RUN_SHARED_KEY: envelope}
    assert latest.status == "completed"
    assert latest.context.responses is None


def test_projector_excludes_other_shared_data() -> None:
    """The projector cannot leak unrelated live shared-data values."""
    ctx = _context(_plan())
    ctx.shared_data["internal"] = object()

    assert plan_run_projector(ctx) == {PLAN_RUN_SHARED_KEY: ctx.shared_data[PLAN_RUN_SHARED_KEY]}


async def test_initial_write_failure_propagates_before_dispatch() -> None:
    """A failed start record prevents the scheduler from dispatching tools."""
    store = SerializingFakeCheckpointStore()
    store.failures = [1]
    manager = CountingToolManager({"tool": {"ok": True}})
    flow = _flow(store, manager)

    with pytest.raises(CheckpointPersistenceError):
        await flow.run_flow(_context(_plan()))

    assert manager.dispatch_counts == {}


async def test_cancellation_releases_lease() -> None:
    """Cancellation does not write a terminal record and releases the lease."""
    gate = asyncio.Event()
    store = SerializingFakeCheckpointStore()
    manager = CountingToolManager({"tool": {"ok": True}}, gates={"tool": gate})
    flow = _flow(store, manager)
    task = asyncio.create_task(flow.run_flow(_context(_plan())))

    for _ in range(1000):
        if manager.calls:
            break
        await asyncio.sleep(0)
    else:
        raise AssertionError("tool was never dispatched before the bounded wait")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert store._leases == {}
