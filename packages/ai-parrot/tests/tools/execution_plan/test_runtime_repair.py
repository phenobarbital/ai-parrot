"""FEAT-585 — ``plan_repair`` attempt accounting, budget, correction and lineage.

Uses the real ``FlowStateSerializer``-backed fake checkpoint store and a
scripted planner client so every planner call — and every checkpoint write
that reserves a repair attempt — can be counted (spec §4
``test_attempt_accounting``, ``test_delta_structural_correction`` and
``test_partial_is_not_error`` toolkit-side coverage, plus the Repair budget
scenarios).
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, List, Optional

import pytest
from pydantic import ValidationError

from parrot.bots.flows.core.checkpoint import ContextSnapshot, FlowCheckpoint
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition
from parrot.bots.flows.plan import ArtifactRef, ExecutionPlan, PlanMetadata, PlanNode
from parrot.clients.base import AbstractClient
from parrot.tools.execution_plan import ExecutionPlanToolkit, PlanDelta, PlanRecoveryConfig
from parrot.tools.execution_plan.models import PLAN_RUN_SHARED_KEY, PlanRunMetadata
from parrot.tools.execution_plan.runs import plan_fingerprint, process_identity, register_plan_checkpoint_types
from parrot.tools.working_memory.tool import WorkingMemoryToolkit

from ._recovery_fakes import CountingToolManager, ScriptedPlannerClient, SerializingFakeCheckpointStore

pytestmark = pytest.mark.asyncio


def _plan() -> ExecutionPlan:
    """Build the sequential checkpointed plan used by repair tests: a -> b -> c."""
    return ExecutionPlan(
        name="repair",
        objective="repair the failed plan",
        metadata=PlanMetadata(checkpoint=True),
        nodes=[
            PlanNode(id="a", tool="a", store_as="a_out"),
            PlanNode(id="b", tool="b", store_as="b_out", depends_on=["a"]),
            PlanNode(id="c", tool="c", store_as="c_out", depends_on=["b"]),
        ],
    )


def _boom(_params: dict) -> None:
    """Tool double that always fails — used for node ``b``'s original attempt."""
    raise RuntimeError("boom")


class _FlakyPlannerClient(AbstractClient):
    """Scripted planner that can raise a raw exception on a given call.

    Each entry in ``steps`` is either a response text or a ``BaseException``
    instance to raise instead — lets a test drive "planner crashed, then
    planner succeeded" sequences that ``ScriptedPlannerClient`` alone cannot.
    """

    def __init__(self, steps: List[Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._steps = list(steps)
        self.calls: List[str] = []

    async def get_client(self) -> Any:
        return self

    async def __aenter__(self) -> "_FlakyPlannerClient":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    async def ask(self, prompt: str, model: Optional[str] = None, **kwargs: Any) -> Any:
        self.calls.append(prompt)
        step = self._steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return SimpleNamespace(output=step)

    async def ask_stream(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def resume(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def invoke(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


async def _failed_run(
    store: SerializingFakeCheckpointStore,
    planner_llm: Any = None,
    **kwargs: Any,
) -> "tuple[ExecutionPlanToolkit, str, CountingToolManager]":
    """Run ``_plan()`` to a terminal partial failure: A ok, B error, C blocked.

    ``b2`` (always succeeds) and ``b3`` (always fails) are pre-registered
    but unused by the original plan, so a repair delta may name either as
    ``b``'s replacement tool without widening the run's frozen allowlist.
    """
    manager = CountingToolManager(
        {
            "a": {"a": 1},
            "b": _boom,
            "c": {"c": 1},
            "b2": {"b2": 1},
            "b3": _boom,
        }
    )
    toolkit = ExecutionPlanToolkit(
        tool_manager=manager,
        working_memory=WorkingMemoryToolkit(),
        checkpoint_store=store,
        planner_llm=planner_llm,
        **kwargs,
    )
    result = await toolkit._run_plan(_plan(), source="plan_name")
    assert result.result["status"] == "partial"
    return toolkit, result.result["run_id"], manager


async def test_refusals_consume_nothing() -> None:
    """Completed, budget-exhausted and unconfigured-planner runs all refuse for free."""
    planner = ScriptedPlannerClient([])

    completed_store = SerializingFakeCheckpointStore()
    completed_manager = CountingToolManager({"a": {"a": 1}, "b": {"b": 1}, "c": {"c": 1}})
    completed_toolkit = ExecutionPlanToolkit(
        tool_manager=completed_manager,
        working_memory=WorkingMemoryToolkit(),
        checkpoint_store=completed_store,
        planner_llm=planner,
    )
    completed = await completed_toolkit._run_plan(_plan(), source="plan_name")
    completed_result = await completed_toolkit.plan_repair(completed.result["run_id"])
    assert completed_result.result["code"] == "run_not_repairable"

    zero_store = SerializingFakeCheckpointStore()
    zero_toolkit, zero_run_id, _ = await _failed_run(
        zero_store, planner, recovery=PlanRecoveryConfig(max_repair_rounds=0)
    )
    zero_result = await zero_toolkit.plan_repair(zero_run_id)
    assert zero_result.result["code"] == "repair_limit_reached"
    zero_resolved = await zero_toolkit._resolver.resolve(zero_run_id)
    assert zero_resolved.metadata.repair_attempts_used == 0

    unconfigured_store = SerializingFakeCheckpointStore()
    unconfigured_toolkit, unconfigured_run_id, _ = await _failed_run(unconfigured_store, planner_llm=None)
    unconfigured_result = await unconfigured_toolkit.plan_repair(unconfigured_run_id)
    assert unconfigured_result.result["code"] == "planner_unavailable"
    unconfigured_resolved = await unconfigured_toolkit._resolver.resolve(unconfigured_run_id)
    assert unconfigured_resolved.metadata.repair_attempts_used == 0

    assert planner.calls == []


async def test_attempt_persisted_before_planner_call() -> None:
    """A planner crash after the reservation write still leaves the attempt spent."""
    store = SerializingFakeCheckpointStore()
    planner = _FlakyPlannerClient([RuntimeError("planner unreachable")])
    toolkit, run_id, _manager = await _failed_run(store, planner)

    with pytest.raises(RuntimeError, match="unreachable"):
        await toolkit.plan_repair(run_id)

    assert len(planner.calls) == 1
    resolved = await toolkit._resolver.resolve(run_id)
    assert resolved.metadata.repair_attempts_used == 1
    assert len(resolved.metadata.repair_children) == 1
    assert resolved.metadata.active_child_run_id is None
    assert store._leases == {}


async def test_invalid_output_consumes_attempt_after_one_correction() -> None:
    """A malformed delta gets exactly one correction call; still invalid consumes the attempt."""
    store = SerializingFakeCheckpointStore()
    planner = ScriptedPlannerClient(["not json", "still not json"])
    toolkit, run_id, _manager = await _failed_run(store, planner)

    result = await toolkit.plan_repair(run_id)

    assert result.result["code"] == "delta_invalid"
    assert len(planner.calls) == 2
    resolved = await toolkit._resolver.resolve(run_id)
    assert resolved.metadata.repair_attempts_used == 1
    assert resolved.metadata.active_child_run_id is None


async def test_successful_repair_runs_only_replacements_and_consolidates() -> None:
    """A one-call accepted delta dispatches only the replacements and consolidates cleanly."""
    store = SerializingFakeCheckpointStore()
    delta = PlanDelta(
        nodes=[
            PlanNode(id="b", tool="b2", store_as="b_out", depends_on=["a"]),
            PlanNode(id="c", tool="c", store_as="c_out", depends_on=["b"]),
        ]
    )
    planner = ScriptedPlannerClient([delta.model_dump_json()])
    toolkit, run_id, manager = await _failed_run(store, planner)

    result = await toolkit.plan_repair(run_id)

    assert result.status == "success"
    assert result.result["status"] == "completed"
    assert result.result["nodes_total"] == 3
    assert result.result["nodes_ok"] == 3
    assert manager.dispatch_counts == {"a": 1, "b": 1, "b2": 1, "c": 1}
    assert len(planner.calls) == 1

    resolved = await toolkit._resolver.resolve(run_id)
    assert resolved.status == "completed"
    assert resolved.metadata.repair_attempts_used == 1
    # The resolver walks the accepted child to a terminal state: the
    # consolidated view is the child's own (leaf) envelope, not the root's —
    # so ``parent_run_id`` (not ``active_child_run_id``, which is the LEAF's
    # own field and is None once nothing further is open) is what proves the
    # lineage walk actually crossed into the accepted child.
    assert resolved.metadata.parent_run_id == run_id
    assert resolved.metadata.root_run_id == run_id


async def test_partial_fanout_not_repairable() -> None:
    """A ``partial`` node (fan-out with some failed items) is never eligible for repair."""
    register_plan_checkpoint_types()
    store = SerializingFakeCheckpointStore()
    plan = ExecutionPlan(
        name="fanout",
        objective="fan out",
        metadata=PlanMetadata(checkpoint=True),
        nodes=[PlanNode(id="a", tool="a", store_as="a_out")],
    )
    metadata = PlanRunMetadata(
        run_id="fanout-run",
        root_run_id="fanout-run",
        plan=plan,
        original_plan=plan,
        source="plan_name",
        started_at=datetime.now(timezone.utc),
        allowed_tools=["a"],
        plan_fingerprint=plan_fingerprint(plan),
        artifact_mode="memory",
        process_id=process_identity(),
    )
    ref = ArtifactRef(node_id="a", status="partial", keys=["a_out"], errors=["1 of 2 items failed"])
    checkpoint = FlowCheckpoint(
        flow_id=metadata.run_id,
        flow_name="fanout",
        checkpoint_id=1,
        created_at=datetime.now(timezone.utc),
        status="failed",
        definition=FlowDefinition(flow=metadata.run_id, nodes=[NodeDefinition(id="a", type="tool", agent_ref="a")]),
        context=ContextSnapshot(
            initial_task=plan.objective,
            results={"a": ref},
            completed_tasks=["a"],
            completion_order=["a"],
            shared_data={PLAN_RUN_SHARED_KEY: metadata.model_dump(mode="json")},
        ),
    )
    await store.put(checkpoint)
    toolkit = ExecutionPlanToolkit(
        tool_manager=CountingToolManager({"a": {"a": 1}}),
        working_memory=WorkingMemoryToolkit(),
        checkpoint_store=store,
        planner_llm=ScriptedPlannerClient([]),
    )

    result = await toolkit.plan_repair(metadata.run_id)

    assert result.result["code"] == "no_repairable_nodes"


async def test_default_two_rounds_survive_a_consumed_attempt() -> None:
    """The default two rounds allow a second attempt after the first is consumed."""
    store = SerializingFakeCheckpointStore()
    second_delta = PlanDelta(nodes=[PlanNode(id="b", tool="b3", store_as="b_out", depends_on=["a"])])
    planner = _FlakyPlannerClient([RuntimeError("planner down"), second_delta.model_dump_json()])
    toolkit, run_id, _manager = await _failed_run(store, planner)

    with pytest.raises(RuntimeError, match="planner down"):
        await toolkit.plan_repair(run_id)

    second = await toolkit.plan_repair(run_id)
    assert second.result["status"] == "partial"
    assert second.result["repair_attempts_used"] == 2

    third = await toolkit.plan_repair(run_id)
    assert third.result["code"] == "repair_limit_reached"
    assert len(planner.calls) == 2


async def test_zero_rounds_disables_without_planner_call() -> None:
    """``max_repair_rounds=0`` refuses every repair without ever calling the planner."""
    store = SerializingFakeCheckpointStore()
    planner = ScriptedPlannerClient([])
    toolkit, run_id, _manager = await _failed_run(store, planner, recovery=PlanRecoveryConfig(max_repair_rounds=0))

    result = await toolkit.plan_repair(run_id)

    assert result.result["code"] == "repair_limit_reached"
    assert planner.calls == []


async def test_plan_supplied_budget_is_rejected() -> None:
    """A plan-level ``max_repair_rounds`` field is rejected at model validation — the host owns the budget."""
    with pytest.raises(ValidationError):
        PlanMetadata(max_repair_rounds=5)
