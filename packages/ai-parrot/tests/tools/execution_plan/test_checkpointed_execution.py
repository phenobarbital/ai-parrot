"""FEAT-585 M6 checkpointed execution and honest fresh-run degradation."""

from __future__ import annotations

import asyncio

import pytest

from parrot.bots.flows.plan import ExecutionPlan, PlanMetadata, PlanNode
from parrot.tools.execution_plan import ExecutionPlanToolkit
from parrot.tools.working_memory.tool import WorkingMemoryToolkit

from ._recovery_fakes import CountingToolManager, SerializingFakeCheckpointStore

pytestmark = pytest.mark.asyncio


def _plan(*, checkpoint: bool = True) -> ExecutionPlan:
    """Return a small valid plan with an explicit checkpoint policy."""
    return ExecutionPlan(
        name="checkpointed",
        objective="run a deterministic tool",
        metadata=PlanMetadata(checkpoint=checkpoint),
        nodes=[PlanNode(id="first", tool="first", store_as="first_result")],
    )


async def test_checkpointed_run_writes_records_and_reports_capability() -> None:
    """A reachable store produces checkpointed UUID-backed plan metadata."""
    store = SerializingFakeCheckpointStore()
    toolkit = ExecutionPlanToolkit(
        tool_manager=CountingToolManager({"first": {"ok": True}}),
        working_memory=WorkingMemoryToolkit(),
        checkpoint_store=store,
    )

    result = await toolkit._run_plan(_plan(), source="plan_name")

    assert result.status == "success"
    assert result.result["checkpoint_enabled"] is True
    assert result.result["run_id"] == result.result["root_run_id"]
    assert store.put_calls >= 2


async def test_no_store_and_metadata_false_both_report_fresh_execution() -> None:
    """No configured tier and plan opt-out never claim checkpoint capability."""
    toolkit = ExecutionPlanToolkit(
        tool_manager=CountingToolManager({"first": {"ok": True}}),
        working_memory=WorkingMemoryToolkit(),
    )
    no_store = await toolkit._run_plan(_plan(), source="plan_name")

    disabled_store = SerializingFakeCheckpointStore()
    disabled = ExecutionPlanToolkit(
        tool_manager=CountingToolManager({"first": {"ok": True}}),
        working_memory=WorkingMemoryToolkit(),
        checkpoint_store=disabled_store,
    )
    metadata_disabled = await disabled._run_plan(_plan(checkpoint=False), source="plan_name")

    for result in (no_store, metadata_disabled):
        assert result.status == "success"
        assert result.result["checkpoint_enabled"] is False
        assert result.result["resume_level"] == "none"
        assert result.result["recovery_reason"] == "checkpoint_unavailable"
    assert disabled_store.put_calls == 0


async def test_probe_outage_degrades_once_and_configuration_error_stops_dispatch() -> None:
    """Outages are cached fresh-run degradation; malformed stores stay explicit."""
    store = SerializingFakeCheckpointStore()
    calls = 0

    async def unavailable(flow_id: str):
        nonlocal calls
        calls += 1
        raise ConnectionError(flow_id)

    store.latest = unavailable  # type: ignore[method-assign]
    toolkit = ExecutionPlanToolkit(
        tool_manager=CountingToolManager({"first": {"ok": True}}),
        working_memory=WorkingMemoryToolkit(),
        checkpoint_store=store,
    )
    assert (await toolkit._run_plan(_plan(), source="plan_name")).result["checkpoint_enabled"] is False
    assert (await toolkit._run_plan(_plan(), source="plan_name")).result["checkpoint_enabled"] is False
    assert calls == 1

    broken = SerializingFakeCheckpointStore()

    async def malformed(_flow_id: str):
        raise TypeError("bad configuration")

    broken.latest = malformed  # type: ignore[method-assign]
    manager = CountingToolManager({"first": {"ok": True}})
    failed = await ExecutionPlanToolkit(
        tool_manager=manager,
        working_memory=WorkingMemoryToolkit(),
        checkpoint_store=broken,
    )._run_plan(_plan(), source="plan_name")
    assert failed.result["code"] == "checkpoint_unavailable"
    assert manager.calls == []


async def test_soft_timeout_summary_carries_checkpoint_envelope() -> None:
    """Timeout reports progress without cancelling the still-running plan task."""
    gate = asyncio.Event()
    toolkit = ExecutionPlanToolkit(
        tool_manager=CountingToolManager({"first": {"ok": True}}, gates={"first": gate}),
        working_memory=WorkingMemoryToolkit(),
        soft_timeout=0.01,
    )

    result = await toolkit._run_plan(_plan(checkpoint=False), source="plan_name")

    assert result.result["status"] == "running"
    assert result.result["uncheckpointed_progress"] is True
    assert result.result["resume_level"] == "none"
    gate.set()
    await next(iter(toolkit._run_tasks.values()))
