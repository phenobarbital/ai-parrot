"""End-to-end integration tests for FEAT-419 (TASK-2185).

Proves the whole design holds together: zero LLM tokens during plan
execution, payloads only in WorkingMemory, `for_each` resumability via
`skip_existing`, allowlist enforcement, and the `AgentCrew.add_tool_node()`
regression (crew's own `ToolNode` is untouched by
`ensure_tool_node_registered(PlanToolNode)`).
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock

import pytest

from parrot.bots.flows.crew import AgentCrew, ToolNode
from parrot.bots.flows.plan import ArtifactRef, ensure_tool_node_registered, PlanToolNode
from parrot.bots.flows.flow.flow import NODE_REGISTRY
from parrot.clients.base import AbstractClient
from parrot.tools.execution_plan.toolkit import ExecutionPlanToolkit
from parrot.tools.working_memory.tool import WorkingMemoryToolkit

_REPO_ROOT = Path(__file__).resolve().parents[5]
_EXAMPLE_PLANS_DIR = _REPO_ROOT / "examples" / "plans"


# ── Shared fakes ─────────────────────────────────────────────────────────────


class _FakeToolManager:
    """``ToolManagerLike`` fake: get_tool/list_tools/execute_tool, records calls."""

    def __init__(self, tools: Dict[str, Any]) -> None:
        self._tools = tools
        self.calls: List[tuple] = []

    def get_tool(self, name: str) -> Optional[Any]:
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        return list(self._tools)

    async def execute_tool(
        self, tool_name: str, parameters: Dict[str, Any],
        permission_context: Optional[Any] = None,
    ) -> Any:
        self.calls.append((tool_name, dict(parameters)))
        payload = self._tools[tool_name]
        return payload(parameters) if callable(payload) else payload


class _ScriptedPlannerClient(AbstractClient):
    """AbstractClient double returning scripted `ask()` responses."""

    def __init__(self, responses: List[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._responses = list(responses)
        self.calls: List[str] = []

    async def get_client(self) -> Any:
        return self

    async def __aenter__(self) -> "_ScriptedPlannerClient":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    async def ask(self, prompt: str, model: Optional[str] = None, **kwargs: Any) -> Any:
        self.calls.append(prompt)
        return SimpleNamespace(output=self._responses.pop(0))

    async def ask_stream(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def resume(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def invoke(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


@pytest.fixture
def wm_toolkit() -> WorkingMemoryToolkit:
    return WorkingMemoryToolkit()


async def _s3_filter_reports(scanner: str, date: str) -> Dict[str, Any]:
    return {"keys": ["r1.json", "r2.json"]}


async def _s3_get_latest_report(key: str) -> Dict[str, Any]:
    return {"findings": [{"severity": "critical"}], "source": key}


async def _compare_scans(current: Any, window_days: int) -> Dict[str, Any]:
    return {"new": [{"id": "f1"}], "resolved": []}


async def _map_report_to_soc2(findings: Any) -> Dict[str, Any]:
    return {"mappings": [{"control_id": "CC6.1"}]}


class TestEndToEnd:
    async def test_basicagent_end_to_end_zero_tokens_in_loop(self, wm_toolkit) -> None:
        """A real BasicAgent, wired but never asked — the toolkit runs the
        example plan with zero calls to the agent's own LLM client."""
        from parrot.bots.agent import BasicAgent

        agent = BasicAgent(name="SweepAgent")

        # Explicit fail-loud guard: the agent's own LLM must never be
        # touched by plan execution (the feature's headline claim), not
        # just "never observed to be called".
        agent.client.ask = AsyncMock(
            side_effect=AssertionError("agent LLM must never be called during plan execution")
        )

        for name, fn in (
            ("s3_filter_reports", _s3_filter_reports),
            ("s3_get_latest_report", _s3_get_latest_report),
            ("compare_scans", _compare_scans),
            ("map_report_to_soc2", _map_report_to_soc2),
        ):
            agent.tool_manager.register_tool(
                name=name, description=name,
                input_schema={"type": "object", "properties": {}}, function=fn,
            )

        example_plan_path = _EXAMPLE_PLANS_DIR / "daily_security_sweep.json"
        assert example_plan_path.exists(), f"missing example plan at {example_plan_path}"
        example_plan_text = example_plan_path.read_text().replace(
            "{params.date}", "2026-08-06"
        )
        planner = _ScriptedPlannerClient([example_plan_text])

        toolkit = ExecutionPlanToolkit(
            tool_manager=agent.tool_manager,
            working_memory=wm_toolkit,
            planner_llm=planner,
            soft_timeout=10.0,
        )

        result = await toolkit.plan_execute(objective="run the daily security sweep")

        assert result.status == "success"
        # Exactly one authoring call — the example plan is valid as-is, no
        # repair round needed. Bounded well under the spec's "≤2" ceiling.
        assert len(planner.calls) == 1
        # Manifest stays small regardless of the payload sizes it summarizes.
        manifest_json = json.dumps(result.result)
        assert len(manifest_json) < 2000
        # No payload BODY leaked. "critical"/"n_findings"/"findings" all
        # legitimately appear (the plan's own `objective` text, and small
        # structural facet names/values) — the report *filename* below is
        # the actual payload marker: it only exists inside the fake tool's
        # returned body, never in a facet, node id, or the objective text.
        assert "r1.json" not in manifest_json
        assert "r2.json" not in manifest_json
        assert result.result["nodes_ok"] == 4
        # BasicAgent's class body is untouched — no monkeypatching of the
        # class itself (only an instance-level test double on this one
        # instance's client.ask, guarding the assertion above).
        assert "plan_execute" not in type(agent).__dict__
        assert "plan_status" not in type(agent).__dict__

    async def test_300_item_fanout_resumable(self, wm_toolkit) -> None:
        """A crash mid-run (simulated: half the keys already stored) only
        re-executes the missing items, via `for_each.skip_existing`."""
        manager = _FakeToolManager(
            {
                "list_items": {"keys": [f"item_{i}" for i in range(300)]},
                "get_item": {"ok": True},
            }
        )
        toolkit = ExecutionPlanToolkit(
            tool_manager=manager, working_memory=wm_toolkit, soft_timeout=30.0,
        )
        plan_json = {
            "name": "fanout-300",
            "objective": "resumable 300-item fan-out",
            "nodes": [
                {"id": "listing", "tool": "list_items", "store_as": "listing"},
                {
                    "id": "fetch", "tool": "get_item", "args": {"key": "{item}"},
                    "store_as": "report_{index}", "depends_on": ["listing"],
                    "for_each": {"source": "{artifacts.listing}", "select": "keys[]"},
                },
            ],
        }

        # Simulate a prior run that died after storing 150 of 300 items.
        for i in range(150):
            wm_toolkit._catalog.put_generic(f"report_{i}", {"ok": True})

        from parrot.bots.flows.plan import ExecutionPlan

        plan = ExecutionPlan.model_validate(plan_json)
        result = await toolkit._run_plan(plan, source="plan_name")

        assert result.status == "success"
        assert result.result["nodes_ok"] == 2  # listing + fetch, both fully "ok"
        # Only the 150 missing items were actually dispatched.
        get_item_calls = [c for c in manager.calls if c[0] == "get_item"]
        assert len(get_item_calls) == 150
        # The fan-out node's manifest artifact still reports all 300 items.
        run_id = next(iter(toolkit._runs))
        fetch_ref = next(
            ref for ref in toolkit._runs[run_id].manifest.artifacts if ref.node_id == "fetch"
        )
        assert fetch_ref.item_count == 300
        assert len(fetch_ref.keys) == 300

    async def test_no_payload_in_flowcontext_results(self, wm_toolkit) -> None:
        """Every `ctx.results` value for a plan node is an ArtifactRef."""
        big_payload = {"findings": [{"id": i} for i in range(500)]}
        manager = _FakeToolManager({"fast": big_payload})
        toolkit = ExecutionPlanToolkit(
            tool_manager=manager, working_memory=wm_toolkit, soft_timeout=5.0,
        )
        from parrot.bots.flows.plan import ExecutionPlan, PlanNode

        plan = ExecutionPlan(
            name="single", objective="single node",
            nodes=[PlanNode(id="n1", tool="fast", store_as="k1")],
        )

        await toolkit._run_plan(plan, source="plan_name")
        run_id = next(iter(toolkit._runs))
        ctx = toolkit._run_contexts[run_id]

        plan_node_ids = {node.id for node in plan.nodes}
        for node_id, value in ctx.results.items():
            if node_id in plan_node_ids:
                assert isinstance(value, ArtifactRef)
        assert "findings" not in str(ctx.results)

    async def test_agentcrew_add_tool_node_regression(self) -> None:
        """`ensure_tool_node_registered(PlanToolNode)` must not affect
        `AgentCrew.add_tool_node()`, which builds crew's own `ToolNode`
        directly — never through `NODE_REGISTRY`."""
        from _crew_test_helpers import DummyAgent, DummyTool  # noqa: PLC0415

        ensure_tool_node_registered(PlanToolNode)
        assert NODE_REGISTRY["tool"] is PlanToolNode

        crew = AgentCrew(
            name="RegressionCrew", agents=[DummyAgent("a")],
            auto_configure=False, persist_results=False,
            enable_execution_wiki=False,
        )
        tool = DummyTool("fetcher", result="REGRESSION-PAYLOAD")
        node = crew.add_tool_node(tool, "fetch")

        assert isinstance(node, ToolNode)
        assert not isinstance(node, PlanToolNode)

        result = await crew.run_sequential(
            "start", agent_sequence=["a", "fetch"], generate_summary=False,
        )
        assert result.status == "completed"
        assert len(tool.calls) == 1

    async def test_allowlist_blocks_before_execution(self, wm_toolkit, tmp_path) -> None:
        """A plan naming a registered-but-not-allowlisted tool never runs,
        exercised end-to-end through `plan_execute(plan_name=...)`."""
        manager = _FakeToolManager(
            {"safe_tool": {"ok": True}, "dangerous_tool": {"ok": True}}
        )
        toolkit = ExecutionPlanToolkit(
            tool_manager=manager, working_memory=wm_toolkit,
            allowed_tools=["safe_tool"], plans_dir=tmp_path, soft_timeout=5.0,
        )
        plan_json = {
            "name": "blocked-plan",
            "objective": "uses a non-allowlisted tool",
            "nodes": [{"id": "n1", "tool": "dangerous_tool", "store_as": "k1"}],
        }
        (tmp_path / "blocked-plan.json").write_text(json.dumps(plan_json))

        result = await toolkit.plan_execute(plan_name="blocked-plan")

        assert result.status == "error"
        assert "invalid" in result.error.lower()
        assert manager.calls == []
        assert toolkit._runs == {}
