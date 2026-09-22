"""FEAT-585 — plan_resume recovery behaviour using the checkpoint fake store."""

from __future__ import annotations

import asyncio

import pytest

from parrot.bots.flows.plan import ExecutionPlan, PlanMetadata, PlanNode
from parrot.tools.execution_plan import ExecutionPlanToolkit
from parrot.tools.working_memory.tool import WorkingMemoryToolkit

from ._recovery_fakes import CountingToolManager, SerializingFakeCheckpointStore

pytestmark = pytest.mark.asyncio


def _plan() -> ExecutionPlan:
    """Build the sequential checkpointed plan used by continuation tests."""
    return ExecutionPlan(
        name="resume",
        objective="continue the interrupted plan",
        metadata=PlanMetadata(checkpoint=True),
        nodes=[
            PlanNode(id="a", tool="a", store_as="a_out"),
            PlanNode(id="b", tool="b", store_as="b_out", depends_on=["a"]),
            PlanNode(id="c", tool="c", store_as="c_out", depends_on=["b"]),
        ],
    )


async def _interrupted_run(store: SerializingFakeCheckpointStore) -> tuple[str, CountingToolManager]:
    """Checkpoint A and B, then cancel C while it is held at a gate."""
    gate = asyncio.Event()
    manager = CountingToolManager({"a": {"a": 1}, "b": {"b": 1}, "c": {"c": 1}}, gates={"c": gate})
    toolkit = ExecutionPlanToolkit(
        tool_manager=manager,
        working_memory=WorkingMemoryToolkit(),
        checkpoint_store=store,
        soft_timeout=0.01,
    )

    result = await toolkit._run_plan(_plan(), source="plan_name")
    run_id = result.result["run_id"]
    task = toolkit._run_tasks[run_id]
    for _ in range(100):
        if manager.dispatch_counts.get("c") == 1:
            break
        await asyncio.sleep(0)
    assert manager.dispatch_counts == {"a": 1, "b": 1, "c": 1}
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    return run_id, manager


async def test_resume_unknown_and_not_resumable_codes() -> None:
    """Unknown and terminal identities refuse without dispatching a tool."""
    store = SerializingFakeCheckpointStore()
    manager = CountingToolManager({"a": {"a": 1}, "b": {"b": 1}, "c": {"c": 1}})
    toolkit = ExecutionPlanToolkit(
        tool_manager=manager, working_memory=WorkingMemoryToolkit(), checkpoint_store=store
    )

    unknown = await toolkit.plan_resume("unknown")
    completed = await toolkit._run_plan(_plan(), source="plan_name")
    terminal = await toolkit.plan_resume(completed.result["run_id"])

    assert unknown.result["code"] == "missing_or_expired"
    assert terminal.result["code"] == "run_not_resumable"
    assert manager.dispatch_counts == {"a": 1, "b": 1, "c": 1}


async def test_resume_does_not_redispatch_completed_and_completes_rest() -> None:
    """The completion frontier retains A/B and dispatches only the interrupted C."""
    store = SerializingFakeCheckpointStore()
    run_id, manager = await _interrupted_run(store)
    resumed = ExecutionPlanToolkit(
        tool_manager=manager, working_memory=WorkingMemoryToolkit(), checkpoint_store=store
    )
    manager._gates["c"].set()

    result = await resumed.plan_resume(run_id)

    assert result.status == "success"
    assert result.result["status"] == "completed"
    assert manager.dispatch_counts == {"a": 1, "b": 1, "c": 2}
    assert [ref["node_id"] for ref in result.result["artifacts"]] == ["a", "b", "c"]
    assert store._leases == {}


async def test_resume_refuses_policy_and_fingerprint_drift() -> None:
    """Current policy and persisted fingerprint are checked before any continuation lease."""
    store = SerializingFakeCheckpointStore()
    run_id, manager = await _interrupted_run(store)
    narrowed = ExecutionPlanToolkit(
        tool_manager=manager,
        working_memory=WorkingMemoryToolkit(),
        checkpoint_store=store,
        allowed_tools=["a", "b"],
    )

    result = await narrowed.plan_resume(run_id)

    assert result.result["code"] == "policy_mismatch"
    assert manager.dispatch_counts == {"a": 1, "b": 1, "c": 1}


async def test_resume_never_calls_planner() -> None:
    """Direct resume uses the persisted plan and never invokes a planner client."""
    store = SerializingFakeCheckpointStore()
    run_id, manager = await _interrupted_run(store)
    toolkit = ExecutionPlanToolkit(
        tool_manager=manager,
        working_memory=WorkingMemoryToolkit(),
        checkpoint_store=store,
        planner_llm=object(),
    )
    manager._gates["c"].set()

    result = await toolkit.plan_resume(run_id)

    assert result.status == "success"
    assert manager.dispatch_counts == {"a": 1, "b": 1, "c": 2}
