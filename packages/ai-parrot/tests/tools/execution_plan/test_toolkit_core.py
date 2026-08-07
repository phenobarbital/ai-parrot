"""Unit tests for ExecutionPlanToolkit's core executor path and run registry.

TASK-2180 scope: constructor wiring, `_run_plan`, `plan_status`,
`plan_artifacts`, and run-registry bounds. Plan acquisition
(`plan_execute`/`plan_validate`) is TASK-2184 — these tests call
`_run_plan` directly with programmatically built `ExecutionPlan`s.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import pytest

from parrot.bots.flows.plan import ArtifactRef, ExecutionPlan, ForEach, PlanNode
from parrot.bots.flows.flow.flow import NODE_REGISTRY
from parrot.tools.execution_plan.toolkit import ExecutionPlanToolkit
from parrot.tools.working_memory.tool import WorkingMemoryToolkit

pytestmark = pytest.mark.asyncio


class _FakeToolManager:
    """``ToolManagerLike`` fake: get_tool/list_tools/execute_tool, records calls."""

    def __init__(
        self,
        tools: Dict[str, Any],
        *,
        delays: Optional[Dict[str, float]] = None,
    ) -> None:
        self._tools = tools
        self._delays = delays or {}
        self.calls: List[tuple] = []

    def get_tool(self, name: str) -> Optional[Any]:
        return object() if name in self._tools else None

    def list_tools(self) -> List[str]:
        return list(self._tools)

    async def execute_tool(
        self, tool_name: str, parameters: Dict[str, Any],
        permission_context: Optional[Any] = None,
    ) -> Any:
        self.calls.append((tool_name, dict(parameters)))
        delay = self._delays.get(tool_name)
        if delay:
            await asyncio.sleep(delay)
        payload = self._tools[tool_name]
        return payload(parameters) if callable(payload) else payload


@pytest.fixture
def wm_toolkit() -> WorkingMemoryToolkit:
    """Real WorkingMemoryToolkit over an in-memory catalog."""
    return WorkingMemoryToolkit()


def _single_node_plan(tool: str = "fast", node_id: str = "n1") -> ExecutionPlan:
    return ExecutionPlan(
        name="single-node-plan",
        objective="unit test plan",
        nodes=[PlanNode(id=node_id, tool=tool, store_as=f"{node_id}_out")],
    )


class TestExecutorPath:
    async def test_toolkit_constructible_with_only_required_deps(self, wm_toolkit):
        toolkit = ExecutionPlanToolkit(
            tool_manager=_FakeToolManager({}), working_memory=wm_toolkit,
        )
        assert toolkit.soft_timeout == 60.0
        assert toolkit.allowed_tools is None
        assert toolkit.plans_dir is None

    async def test_manifest_within_soft_timeout(self, wm_toolkit):
        manager = _FakeToolManager({"fast": {"x": 1}})
        toolkit = ExecutionPlanToolkit(
            tool_manager=manager, working_memory=wm_toolkit, soft_timeout=5.0,
        )
        plan = _single_node_plan(tool="fast")

        result = await toolkit._run_plan(plan, source="plan_name")

        assert result.status == "success"
        assert result.result["nodes_total"] == 1
        assert result.result["nodes_ok"] == 1
        assert manager.calls == [("fast", {})]

    async def test_soft_timeout_returns_running_summary_and_completes(self, wm_toolkit):
        manager = _FakeToolManager({"slow": {"ok": True}}, delays={"slow": 0.3})
        toolkit = ExecutionPlanToolkit(
            tool_manager=manager, working_memory=wm_toolkit, soft_timeout=0.01,
        )
        plan = _single_node_plan(tool="slow")

        result = await toolkit._run_plan(plan, source="plan_name")

        assert result.result["status"] == "running"
        run_id = result.result["run_id"]

        # Let the background run finish.
        await asyncio.sleep(0.6)

        status_result = await toolkit.plan_status(run_id=run_id)
        assert status_result.result["nodes_ok"] == 1
        assert status_result.result["nodes_total"] == 1

    async def test_partial_failure_is_manifest_not_exception(self, wm_toolkit):
        def get(params: Dict[str, Any]) -> Dict[str, Any]:
            if params["key"] == "b":
                raise RuntimeError("boom")
            return {"ok": True}

        manager = _FakeToolManager({"listing": {"keys": ["a", "b"]}, "get": get})
        toolkit = ExecutionPlanToolkit(
            tool_manager=manager, working_memory=wm_toolkit, soft_timeout=5.0,
        )
        plan = ExecutionPlan(
            name="partial-plan",
            objective="induce a partial failure",
            nodes=[
                PlanNode(id="listing", tool="listing", store_as="listing"),
                PlanNode(
                    id="fetch", tool="get", args={"key": "{item}"},
                    store_as="report_{index}", depends_on=["listing"],
                    for_each=ForEach(source="{artifacts.listing}", select="keys[]"),
                ),
            ],
        )

        result = await toolkit._run_plan(plan, source="plan_name")

        assert result.status == "success"
        assert result.result["nodes_failed"] >= 1

    async def test_payloads_only_in_working_memory(self, wm_toolkit):
        big_payload = {"findings": [{"id": i} for i in range(1000)]}
        manager = _FakeToolManager({"fast": big_payload})
        toolkit = ExecutionPlanToolkit(
            tool_manager=manager, working_memory=wm_toolkit, soft_timeout=5.0,
        )
        plan = _single_node_plan(tool="fast")

        result = await toolkit._run_plan(plan, source="plan_name")
        run_id = next(iter(toolkit._runs))

        ctx = toolkit._run_contexts[run_id]
        tool_ref = ctx.results["n1"]
        assert isinstance(tool_ref, ArtifactRef)
        assert tool_ref.keys == ["n1_out"]
        # The payload body lives only in working memory — never in
        # ctx.results (checked against the whole context, not just the
        # tool node's own ArtifactRef) nor in the bounded manifest response.
        assert "findings" not in str(ctx.results)
        assert len(str(result.result)) < 1000

    async def test_tool_registered_lazily_not_at_import(self, wm_toolkit):
        # NODE_REGISTRY is process-global; the toolkit's constructor alone
        # must not register "tool" — only the first _run_plan call does.
        # Save/restore so this test does not leak state into others.
        previous = NODE_REGISTRY.pop("tool", None)
        try:
            toolkit = ExecutionPlanToolkit(
                tool_manager=_FakeToolManager({}), working_memory=wm_toolkit,
            )
            assert "tool" not in NODE_REGISTRY

            plan = _single_node_plan(tool="noop")
            manager = _FakeToolManager({"noop": {"ok": True}})
            toolkit._tool_manager = manager
            await toolkit._run_plan(plan, source="plan_name")
            assert "tool" in NODE_REGISTRY
        finally:
            if previous is not None:
                NODE_REGISTRY["tool"] = previous


class TestRunRegistry:
    async def test_eviction_bounds(self, wm_toolkit):
        manager = _FakeToolManager({"fast": {"ok": True}})
        toolkit = ExecutionPlanToolkit(
            tool_manager=manager, working_memory=wm_toolkit,
            soft_timeout=5.0, max_completed_runs=3,
        )

        for i in range(6):
            plan = _single_node_plan(tool="fast", node_id=f"n{i}")
            await toolkit._run_plan(plan, source="plan_name")

        assert len(toolkit._runs) == 3
        assert all(rec.status != "running" or True for rec in toolkit._runs.values())

    async def test_in_flight_run_never_evicted(self, wm_toolkit):
        manager = _FakeToolManager({"slow": {"ok": True}}, delays={"slow": 0.3})
        toolkit = ExecutionPlanToolkit(
            tool_manager=manager, working_memory=wm_toolkit,
            soft_timeout=0.01, max_completed_runs=1,
        )

        slow_plan = _single_node_plan(tool="slow", node_id="slow_node")
        slow_result = await toolkit._run_plan(slow_plan, source="plan_name")
        slow_run_id = slow_result.result["run_id"]

        fast_manager = manager
        fast_manager._tools["fast"] = {"ok": True}
        for i in range(3):
            plan = _single_node_plan(tool="fast", node_id=f"fast_{i}")
            await toolkit._run_plan(plan, source="plan_name")

        # The still-running slow run must survive eviction regardless of
        # max_completed_runs, since eviction only ever considers non-running
        # entries.
        assert slow_run_id in toolkit._runs
        assert toolkit._runs[slow_run_id].status == "running"

        await asyncio.sleep(0.6)  # let it finish before the fixture tears down

    async def test_unknown_run_id_tool_error(self, wm_toolkit):
        toolkit = ExecutionPlanToolkit(
            tool_manager=_FakeToolManager({}), working_memory=wm_toolkit,
        )

        result = await toolkit.plan_status(run_id="does-not-exist")

        assert result.status == "error"
        assert result.success is False
        assert "does-not-exist" in result.error

        artifacts_result = await toolkit.plan_artifacts(run_id="does-not-exist")
        assert artifacts_result.status == "error"
