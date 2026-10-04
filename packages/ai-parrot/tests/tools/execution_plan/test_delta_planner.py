"""FEAT-585 M5 — PlanPlanner.replan / repair_delta call bounds and prompt contents."""

from __future__ import annotations

import json

import pytest

from parrot.bots.flows.plan import ArtifactRef, ExecutionManifest, ExecutionPlan, PlanNode
from parrot.bots.flows.plan.validator import ValidationIssue, ValidationReport
from parrot.tools.execution_plan.catalog import ToolCatalogEntry
from parrot.tools.execution_plan.models import PlanDelta
from parrot.tools.execution_plan.planner import PlanAuthoringError, PlanPlanner

from ._recovery_fakes import ScriptedPlannerClient

pytestmark = pytest.mark.asyncio

_ELIGIBLE = frozenset({"b", "d"})


def _catalog() -> list[ToolCatalogEntry]:
    return [
        ToolCatalogEntry(name="tool_a", description="First tool", args_summary=[]),
        ToolCatalogEntry(name="tool_b", description="Second tool", args_summary=[]),
        ToolCatalogEntry(name="tool_b2", description="Second tool, replacement", args_summary=[]),
        ToolCatalogEntry(name="tool_d", description="Fourth tool", args_summary=[]),
    ]


def _plan() -> ExecutionPlan:
    return ExecutionPlan(
        name="repair_demo",
        objective="Demonstrate delta planning.",
        nodes=[
            PlanNode(id="a", tool="tool_a", args={}, store_as="a_out"),
            PlanNode(id="b", tool="tool_b", args={}, store_as="b_out", depends_on=["a"]),
            PlanNode(id="c", tool="tool_a", args={}, store_as="c_out", depends_on=["a"]),
            PlanNode(id="d", tool="tool_d", args={}, store_as="d_out", depends_on=["a"]),
        ],
    )


def _manifest(*, secret_key: str = "a_out") -> ExecutionManifest:
    return ExecutionManifest(
        plan_name="repair_demo",
        objective="Demonstrate delta planning.",
        artifacts=[
            # `keys` names the working-memory key(s) a node wrote — never the stored
            # body. A distinctive value here proves `_render_failures` never touches it.
            ArtifactRef(node_id="a", status="ok", keys=[secret_key]),
            ArtifactRef(node_id="b", status="error", errors=["boom b"]),
            ArtifactRef(node_id="c", status="skipped"),
            ArtifactRef(node_id="d", status="error", errors=["boom d"]),
        ],
        nodes_total=4,
        nodes_ok=1,
        nodes_skipped=1,
        nodes_failed=2,
    )


def _valid_delta_json() -> dict:
    return {
        "nodes": [
            {"id": "b", "tool": "tool_b2", "args": {}, "store_as": "b_out", "depends_on": ["a"]},
        ]
    }


async def test_replan_makes_exactly_one_call_and_returns_delta() -> None:
    client = ScriptedPlannerClient([json.dumps(_valid_delta_json())])
    planner = PlanPlanner(client, _catalog())

    delta = await planner.replan(_plan(), _manifest(), eligible_node_ids=_ELIGIBLE)

    assert isinstance(delta, PlanDelta)
    assert [node.id for node in delta.nodes] == ["b"]
    assert len(client.calls) == 1


async def test_replan_prompt_contains_rules_eligible_ids_and_no_bodies() -> None:
    client = ScriptedPlannerClient([json.dumps(_valid_delta_json())])
    planner = PlanPlanner(client, _catalog())

    await planner.replan(_plan(), _manifest(secret_key="SECRET-KEY-CONTENTS"), eligible_node_ids=_ELIGIBLE)

    prompt = client.calls[0]
    assert "repairing a FAILED ExecutionPlan" in prompt
    assert "['b', 'd']" in prompt
    assert '"name": "repair_demo"' in prompt
    # Per-node error text is legitimately rendered (truncated); `ArtifactRef.keys`
    # contents — and a fortiori any stored artifact body — must never appear.
    assert "boom b" in prompt
    assert "SECRET-KEY-CONTENTS" not in prompt


async def test_replan_rejects_non_eligible_ids() -> None:
    stray_delta = {
        "nodes": [
            {"id": "c", "tool": "tool_a", "args": {}, "store_as": "c_out", "depends_on": ["a"]},
        ]
    }
    client = ScriptedPlannerClient([json.dumps(stray_delta)])
    planner = PlanPlanner(client, _catalog())

    with pytest.raises(PlanAuthoringError, match="non-eligible node ids"):
        await planner.replan(_plan(), _manifest(), eligible_node_ids=_ELIGIBLE)


async def test_replan_rejects_non_json_and_invalid_delta() -> None:
    client = ScriptedPlannerClient(["not json at all {"])
    planner = PlanPlanner(client, _catalog())

    with pytest.raises(PlanAuthoringError, match="not valid JSON"):
        await planner.replan(_plan(), _manifest(), eligible_node_ids=_ELIGIBLE)

    client2 = ScriptedPlannerClient([json.dumps({"nodes": []})])
    planner2 = PlanPlanner(client2, _catalog())

    with pytest.raises(PlanAuthoringError, match="failed PlanDelta validation"):
        await planner2.replan(_plan(), _manifest(), eligible_node_ids=_ELIGIBLE)


async def test_repair_delta_makes_exactly_one_call_with_report_text() -> None:
    bad_delta_json = {"nodes": [{"id": "b", "tool": "tool_forbidden", "args": {}, "store_as": "b_out2"}]}
    report = ValidationReport(
        issues=[ValidationIssue(node_id="b", code="delta_store_as_changed", message="store_as must not change")]
    )
    client = ScriptedPlannerClient([json.dumps(_valid_delta_json())])
    planner = PlanPlanner(client, _catalog())

    delta = await planner.repair_delta(bad_delta_json, report, plan=_plan(), eligible_node_ids=_ELIGIBLE)

    assert isinstance(delta, PlanDelta)
    assert len(client.calls) == 1
    prompt = client.calls[0]
    assert str(report) in prompt
    assert json.dumps(bad_delta_json) in prompt


async def test_failures_summary_is_bounded() -> None:
    plan = _plan()
    artifacts = [ArtifactRef(node_id="a", status="ok", keys=["a_out"])]
    for i in range(30):
        artifacts.append(ArtifactRef(node_id=f"n{i}", status="error", errors=["x" * 1000]))
    manifest = ExecutionManifest(
        plan_name="repair_demo",
        objective="Demonstrate delta planning.",
        artifacts=artifacts,
        nodes_total=31,
        nodes_ok=1,
        nodes_skipped=0,
        nodes_failed=30,
    )
    client = ScriptedPlannerClient([json.dumps(_valid_delta_json())])
    planner = PlanPlanner(client, _catalog())

    await planner.replan(plan, manifest, eligible_node_ids=_ELIGIBLE)

    prompt = client.calls[0]
    failures_section = prompt.split("Failures:\n", 1)[1]
    failure_lines = [line for line in failures_section.splitlines() if line.startswith("- n")]
    assert len(failure_lines) == 20
    # Each error is truncated to 300 chars (the "x" run in this test).
    for line in failure_lines:
        assert line.count("x") <= 300
