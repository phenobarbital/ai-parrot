"""FEAT-590: allowlist + repair are delegate-aware."""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel

from parrot.bots.flows.plan.models import ArtifactRef, DelegatePlanNode, ExecutionPlan, PlanNode
from parrot.tools.execution_plan.catalog import check_allowlist
from parrot.tools.execution_plan.models import PlanDelta, PlanRun, PlanRunMetadata
from parrot.tools.execution_plan.repair import validate_delta

from ...bots.flows.plan._delegate_fakes import FakeDelegate, FakeTool, FakeToolManager


class _EmptyArgs(BaseModel):
    """Schema for tools that take no arguments."""


def _plan() -> ExecutionPlan:
    """Build a mixed tool and delegate plan."""
    return ExecutionPlan(
        name="delegate-repair",
        objective="Test delegate-aware repair validation.",
        nodes=[
            DelegatePlanNode(
                id="pick",
                instruction="Choose a supported tool.",
                tools=["tool_a", "tool_b"],
                store_as="picked",
            ),
            PlanNode(id="run", tool="tool_a", args={}, store_as="result", depends_on=["pick"]),
        ],
    )


def _run(plan: ExecutionPlan, refs: list[ArtifactRef]) -> PlanRun:
    """Build a terminal failed run around ``plan``."""
    metadata = PlanRunMetadata(
        run_id="run-1",
        root_run_id="run-1",
        parent_run_id=None,
        plan=plan,
        original_plan=plan,
        source="objective",
        started_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
        allowed_tools=["tool_a", "tool_b"],
        plan_fingerprint="a" * 64,
        artifact_mode="memory",
    )
    return PlanRun(
        metadata=metadata,
        checkpoint_id=1,
        status="failed",
        refs=refs,
        nodes_done=len(refs),
        checkpoint_enabled=True,
        resume_level="process",
        resumable=False,
        dispatched_node_ids=[ref.node_id for ref in refs],
    )


def _tool_manager() -> FakeToolManager:
    """Return a manager with delegate-safe tools."""
    return FakeToolManager([FakeTool("tool_a", _EmptyArgs), FakeTool("tool_b", _EmptyArgs)], {})


def test_allowlist_covers_delegate_tools() -> None:
    """Every disallowed delegate candidate receives an allowlist issue."""
    issues = check_allowlist(_plan(), ["tool_a"])
    assert [(issue.node_id, issue.code, issue.message) for issue in issues] == [
        (
            "pick",
            "tool_not_allowed",
            "Tool 'tool_b' is not in the allowed_tools list. Allowed: ['tool_a'].",
        )
    ]


def test_allowlist_tool_only_unchanged() -> None:
    """Tool-only plan messages retain their previous shape."""
    plan = ExecutionPlan(
        name="tool-only",
        objective="Check existing behavior.",
        nodes=[PlanNode(id="run", tool="tool_b", args={}, store_as="result")],
    )
    issues = check_allowlist(plan, ["tool_a"])
    assert [(issue.node_id, issue.code, issue.message) for issue in issues] == [
        ("run", "tool_not_allowed", "Tool 'tool_b' is not in the allowed_tools list. Allowed: ['tool_a'].")
    ]


def test_delta_targeting_delegate_rejected() -> None:
    """A delta cannot replace a delegate node with a tool node."""
    run = _run(_plan(), [ArtifactRef(node_id="pick", status="error", errors=["failed"])])
    delta = PlanDelta(nodes=[PlanNode(id="pick", tool="tool_a", args={}, store_as="picked")])
    report = validate_delta(delta, run=run, tool_manager=_tool_manager(), allowed_tools=["tool_a", "tool_b"])
    assert "delta_delegate_not_repairable" in {issue.code for issue in report.errors}


def test_delta_on_tool_node_in_mixed_plan_validates() -> None:
    """Forwarded delegates let a merged mixed plan validate successfully."""
    run = _run(
        _plan(),
        [
            ArtifactRef(node_id="pick", status="ok", keys=["picked"]),
            ArtifactRef(node_id="run", status="error", errors=["failed"]),
        ],
    )
    delta = PlanDelta(nodes=[PlanNode(id="run", tool="tool_b", args={}, store_as="result", depends_on=["pick"])])
    report = validate_delta(
        delta,
        run=run,
        tool_manager=_tool_manager(),
        allowed_tools=["tool_a", "tool_b"],
        delegates=[FakeDelegate([])],
    )
    assert report.ok, report
    assert "no_delegate_configured" not in {issue.code for issue in report.errors}
