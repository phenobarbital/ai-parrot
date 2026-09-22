"""FEAT-585 M6 — recovery configuration and resolver-backed status/artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

import pytest

from parrot.bots.flows.core.checkpoint import ContextSnapshot, FlowCheckpoint
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition
from parrot.bots.flows.plan import ArtifactRef, ExecutionPlan, PlanNode
from parrot.tools.execution_plan import (
    ExecutionPlanToolkit,
    PlanDelta,
    PlanRecoveryConfig,
    PlanRepairArgs,
    PlanResumeArgs,
    PlanRunError,
    PlanRunManifest,
    PlanRunMetadata,
    PlanRunSummary,
)
from parrot.tools.execution_plan.models import PLAN_RUN_SHARED_KEY
from parrot.tools.execution_plan.runs import plan_fingerprint, process_identity, register_plan_checkpoint_types
from parrot.tools.working_memory.tool import WorkingMemoryToolkit
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig, TaskMemoryRuntime

from ._recovery_fakes import CountingToolManager, SerializingFakeCheckpointStore

pytestmark = pytest.mark.asyncio


def _plan() -> ExecutionPlan:
    """Create the one-node execution plan used by toolkit recovery tests."""
    return ExecutionPlan(name="recovery", objective="recover", nodes=[PlanNode(id="step", tool="tool")])


def _metadata(plan: ExecutionPlan, **overrides: Any) -> PlanRunMetadata:
    """Build the persisted plan-run metadata expected by the resolver."""
    run_id = overrides.get("run_id", "checkpoint-run")
    fields: Dict[str, Any] = {
        "run_id": run_id,
        "root_run_id": run_id,
        "parent_run_id": None,
        "plan": plan,
        "original_plan": plan,
        "source": "plan_name",
        "started_at": datetime.now(timezone.utc),
        "allowed_tools": ["tool"],
        "plan_fingerprint": plan_fingerprint(plan),
        "artifact_mode": "memory",
        "process_id": process_identity(),
    }
    fields.update(overrides)
    return PlanRunMetadata(**fields)


def _checkpoint(metadata: PlanRunMetadata, ref: ArtifactRef) -> FlowCheckpoint:
    """Build a terminal checkpoint carrying typed artifact metadata only."""
    return FlowCheckpoint(
        flow_id=metadata.run_id,
        flow_name="execution-plan",
        checkpoint_id=1,
        created_at=datetime.now(timezone.utc),
        status="completed",
        definition=FlowDefinition(
            flow=metadata.run_id,
            nodes=[NodeDefinition(id="step", type="agent", agent_ref="agent")],
        ),
        context=ContextSnapshot(
            initial_task=metadata.plan.objective,
            results={"step": ref},
            completed_tasks=["step"],
            completion_order=["step"],
            shared_data={PLAN_RUN_SHARED_KEY: metadata.model_dump(mode="json")},
        ),
    )


async def test_defaults_select_d1_policy() -> None:
    """An unconfigured toolkit keeps all recovery tiers disabled."""
    toolkit = ExecutionPlanToolkit(tool_manager=CountingToolManager({}), working_memory=WorkingMemoryToolkit())

    assert toolkit.recovery.max_repair_rounds == 2
    assert toolkit._checkpoint_store is None
    assert toolkit._durable_store is None


async def test_store_instances_are_borrowed_and_not_closed_on_cleanup() -> None:
    """Toolkit cleanup leaves caller-owned checkpoint stores open."""
    store = SerializingFakeCheckpointStore()
    closed = False

    async def close() -> None:
        nonlocal closed
        closed = True

    store.close = close  # type: ignore[method-assign]
    toolkit = ExecutionPlanToolkit(
        tool_manager=CountingToolManager({}),
        working_memory=WorkingMemoryToolkit(),
        checkpoint_store=store,
    )

    await toolkit.cleanup()

    assert toolkit._checkpoint_store is store
    assert closed is False


async def test_runtime_without_scope_is_configuration_error() -> None:
    """A borrowed task-memory runtime requires its trusted host scope."""
    runtime = TaskMemoryRuntime(TaskMemoryConfig(enabled=True, durable=False))

    with pytest.raises(ValueError, match="trusted TaskScope"):
        ExecutionPlanToolkit(
            tool_manager=CountingToolManager({}),
            working_memory=WorkingMemoryToolkit(),
            task_memory_runtime=runtime,
        )


async def test_status_and_artifacts_from_checkpoint_only() -> None:
    """Status and refs resolve from checkpoint metadata without artifact restoration."""
    register_plan_checkpoint_types()
    store = SerializingFakeCheckpointStore()
    plan = _plan()
    metadata = _metadata(plan)
    ref = ArtifactRef(node_id="step", status="ok", keys=["output"], bytes_stored=12)
    await store.put(_checkpoint(metadata, ref))
    toolkit = ExecutionPlanToolkit(
        tool_manager=CountingToolManager({}),
        working_memory=WorkingMemoryToolkit(),
        checkpoint_store=store,
    )

    status = await toolkit.plan_status(metadata.run_id)
    artifacts = await toolkit.plan_artifacts(metadata.run_id)

    assert status.status == "success"
    assert status.result["status"] == "completed"
    assert status.result["root_run_id"] == metadata.run_id
    assert status.result["resume_level"] == "process"
    assert status.result["resumable"] is False
    assert artifacts.status == "success"
    assert artifacts.result["artifacts"] == [ref.model_dump(mode="json")]
    assert artifacts.result["checkpoint_enabled"] is True


async def test_unknown_vs_missing_by_tier() -> None:
    """Tier configuration, not an in-process side record, classifies a miss."""
    working_memory = WorkingMemoryToolkit()
    durable = ExecutionPlanToolkit(
        tool_manager=CountingToolManager({}),
        working_memory=working_memory,
        durable_store=SerializingFakeCheckpointStore(durable=True),
    )
    ephemeral = ExecutionPlanToolkit(
        tool_manager=CountingToolManager({}),
        working_memory=working_memory,
        checkpoint_store=SerializingFakeCheckpointStore(),
    )

    unknown = await durable.plan_status("unknown")
    expired = await ephemeral.plan_status("expired")

    assert unknown.result["code"] == "unknown_run"
    assert unknown.result["known_run_ids"] == []
    assert expired.result["code"] == "missing_or_expired"


async def test_legacy_in_process_run_still_answers() -> None:
    """Pre-checkpoint records remain visible with an honest no-resume envelope."""
    toolkit = ExecutionPlanToolkit(
        tool_manager=CountingToolManager({"tool": {"ok": True}}),
        working_memory=WorkingMemoryToolkit(),
    )

    executed = await toolkit._run_plan(_plan(), source="plan_name")
    run_id = executed.result["run_id"]
    status = await toolkit.plan_status(run_id)
    artifacts = await toolkit.plan_artifacts(run_id)

    assert status.status == "success"
    assert status.result["checkpoint_enabled"] is False
    assert status.result["resume_level"] == "none"
    assert artifacts.result["checkpoint_enabled"] is False
    assert artifacts.result["resume_level"] == "none"


async def test_new_exports() -> None:
    """The public package exports the recovery models and tool arguments."""
    assert all(
        exported is not None
        for exported in (
            PlanDelta,
            PlanRecoveryConfig,
            PlanRepairArgs,
            PlanResumeArgs,
            PlanRunError,
            PlanRunManifest,
            PlanRunMetadata,
            PlanRunSummary,
        )
    )
