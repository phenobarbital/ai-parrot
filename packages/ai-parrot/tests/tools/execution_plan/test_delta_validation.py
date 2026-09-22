"""FEAT-585 M5 — delta eligibility/merge/validation matrix (D2, AC7)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Sequence

import pytest

from parrot.bots.flows.plan import ArtifactRef, ExecutionPlan, ForEach, PlanNode
from parrot.tools.execution_plan.models import PlanDelta, PlanRun, PlanRunMetadata
from parrot.tools.execution_plan.repair import (
    eligible_repair_nodes,
    merge_delta,
    protected_node_ids,
    validate_delta,
)

from ._recovery_fakes import CountingToolManager

_ALL_TOOLS = ["tool_a", "tool_b", "tool_b2", "tool_c", "tool_d", "tool_forbidden"]


def _make_plan() -> ExecutionPlan:
    """A plan with one ok node, one for_each node and two plain nodes.

    ``a`` succeeds; ``b`` (fan-out) and ``d`` (plain) are the two eligible
    failures; ``c`` is skipped (protected).
    """
    return ExecutionPlan(
        name="repair_demo",
        objective="Demonstrate repair delta validation.",
        nodes=[
            PlanNode(id="a", tool="tool_a", args={}, store_as="a_out"),
            PlanNode(
                id="b",
                tool="tool_b",
                args={},
                store_as="b_out_{index}",
                depends_on=["a"],
                for_each=ForEach(source="{artifacts.a}", select="items[]", skip_existing=True),
            ),
            PlanNode(id="c", tool="tool_c", args={}, store_as="c_out", depends_on=["a"]),
            PlanNode(id="d", tool="tool_d", args={}, store_as="d_out", depends_on=["a"]),
        ],
    )


def _base_refs() -> List[ArtifactRef]:
    return [
        ArtifactRef(node_id="a", status="ok", keys=["a_out"]),
        ArtifactRef(node_id="b", status="error", errors=["fan-out boom"]),
        ArtifactRef(node_id="c", status="skipped"),
        ArtifactRef(node_id="d", status="error", errors=["boom"]),
    ]


def _run(
    plan: ExecutionPlan,
    refs: List[ArtifactRef],
    *,
    status: str = "failed",
    allowed: Optional[Sequence[str]] = None,
) -> PlanRun:
    """Build a minimal ``PlanRun`` view around ``plan``/``refs``."""
    allowed_tools = list(allowed) if allowed is not None else sorted({node.tool for node in plan.nodes})
    metadata = PlanRunMetadata(
        run_id="run-1",
        root_run_id="run-1",
        parent_run_id=None,
        plan=plan,
        original_plan=plan,
        source="objective",
        started_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
        allowed_tools=allowed_tools,
        plan_fingerprint="a" * 64,
        artifact_mode="memory",
    )
    return PlanRun(
        metadata=metadata,
        checkpoint_id=1,
        status=status,
        refs=refs,
        nodes_done=len(refs),
        checkpoint_enabled=True,
        resume_level="process",
        resumable=False,
        dispatched_node_ids=[ref.node_id for ref in refs],
    )


def _tool_manager() -> CountingToolManager:
    return CountingToolManager({name: object() for name in _ALL_TOOLS})


def _valid_replacement_for_b() -> PlanNode:
    """A replacement for the for_each node ``b`` that preserves its identity."""
    return PlanNode(
        id="b",
        tool="tool_b2",
        args={},
        store_as="b_out_{index}",
        depends_on=["a"],
        for_each=ForEach(source="{artifacts.a}", select="items[]", skip_existing=True),
    )


def _valid_replacement_for_d() -> PlanNode:
    """A replacement for the plain eligible node ``d`` that preserves its identity."""
    return PlanNode(id="d", tool="tool_d", args={}, store_as="d_out", depends_on=["a"])


# --- eligible_repair_nodes / protected_node_ids ------------------------------------


@pytest.mark.parametrize("status", ["failed", "partial"])
def test_eligible_is_error_only_on_terminal_failed_or_partial(status: str) -> None:
    plan = _make_plan()
    run = _run(plan, _base_refs(), status=status)
    assert eligible_repair_nodes(run) == frozenset({"b", "d"})
    assert protected_node_ids(run) == frozenset({"a", "c"})


@pytest.mark.parametrize("status", ["running", "completed"])
def test_eligible_is_empty_for_non_terminal_or_completed_run(status: str) -> None:
    plan = _make_plan()
    run = _run(plan, _base_refs(), status=status)
    assert eligible_repair_nodes(run) == frozenset()
    # Every node is protected when nothing is eligible.
    assert protected_node_ids(run) == frozenset({"a", "b", "c", "d"})


def test_partial_is_not_error() -> None:
    """A partial fan-out cannot be reclassified as an error (D2 guard)."""
    plan = _make_plan()
    refs = [
        ArtifactRef(node_id="a", status="ok", keys=["a_out"]),
        ArtifactRef(node_id="b", status="partial", errors=["some items failed"]),
        ArtifactRef(node_id="c", status="skipped"),
        ArtifactRef(node_id="d", status="error", errors=["boom"]),
    ]
    run = _run(plan, refs, status="partial")
    eligible = eligible_repair_nodes(run)
    assert "b" not in eligible
    assert eligible == frozenset({"d"})
    assert "b" in protected_node_ids(run)


# --- merge_delta --------------------------------------------------------------------


def test_merge_preserves_order_and_metadata() -> None:
    plan = _make_plan()
    delta = PlanDelta(nodes=[_valid_replacement_for_d()])
    merged = merge_delta(plan, delta)
    assert [node.id for node in merged.nodes] == ["a", "b", "c", "d"]
    assert merged.name == plan.name
    assert merged.objective == plan.objective
    assert merged.metadata == plan.metadata
    assert merged.node("d").tool == "tool_d"
    # Untouched nodes are unchanged.
    assert merged.node("a") == plan.node("a")


def test_merge_rejects_unknown_id() -> None:
    plan = _make_plan()
    unknown = PlanNode(id="z", tool="tool_a", args={}, store_as="z_out")
    delta = PlanDelta(nodes=[unknown])
    with pytest.raises(ValueError):
        merge_delta(plan, delta)


# --- validate_delta -------------------------------------------------------------------


def _mutation_new_id() -> PlanDelta:
    node = PlanNode(id="z", tool="tool_a", args={}, store_as="z_out")
    return PlanDelta(nodes=[node])


def _mutation_protected_id() -> PlanDelta:
    node = PlanNode(id="c", tool="tool_c", args={}, store_as="c_out", depends_on=["a"])
    return PlanDelta(nodes=[node])


def _mutation_store_as_changed() -> PlanDelta:
    node = _valid_replacement_for_b().model_copy(update={"store_as": "b_out2_{index}"})
    return PlanDelta(nodes=[node])


def _mutation_depends_on_changed() -> PlanDelta:
    node = _valid_replacement_for_d().model_copy(update={"depends_on": []})
    return PlanDelta(nodes=[node])


def _mutation_for_each_identity_changed() -> PlanDelta:
    node = _valid_replacement_for_b().model_copy(
        update={"for_each": ForEach(source="{artifacts.a}", select="other[]", skip_existing=True)}
    )
    return PlanDelta(nodes=[node])


def _mutation_key_collision() -> PlanDelta:
    node = _valid_replacement_for_d().model_copy(update={"store_as": "a_out"})
    return PlanDelta(nodes=[node])


def _mutation_tool_not_allowed() -> PlanDelta:
    node = _valid_replacement_for_d().model_copy(update={"tool": "tool_forbidden"})
    return PlanDelta(nodes=[node])


@pytest.mark.parametrize(
    "mutation,code",
    [
        (_mutation_new_id, "delta_new_id"),
        (_mutation_protected_id, "delta_protected_id"),
        (_mutation_store_as_changed, "delta_store_as_changed"),
        (_mutation_depends_on_changed, "delta_depends_on_changed"),
        (_mutation_for_each_identity_changed, "delta_for_each_identity_changed"),
        (_mutation_key_collision, "delta_key_collision"),
        (_mutation_tool_not_allowed, "delta_tool_not_allowed"),
    ],
)
def test_validate_delta_codes(mutation, code: str) -> None:
    plan = _make_plan()
    run = _run(plan, _base_refs(), status="failed", allowed=["tool_a", "tool_b", "tool_b2", "tool_c", "tool_d"])
    delta = mutation()
    report = validate_delta(delta, run=run, tool_manager=_tool_manager(), allowed_tools=list(run.metadata.allowed_tools))
    assert not report.ok
    assert code in {issue.code for issue in report.errors}


def test_delta_dependency_on_success_validates_without_listing_parent() -> None:
    """R5: a replacement may depend on a successful node the delta omits."""
    plan = _make_plan()
    run = _run(plan, _base_refs(), status="failed", allowed=["tool_a", "tool_b", "tool_b2", "tool_c", "tool_d"])
    # Replace only the eligible for_each node "b"; its dependency "a" (ok) is
    # not listed in the delta at all.
    delta = PlanDelta(nodes=[_valid_replacement_for_b()])
    report = validate_delta(delta, run=run, tool_manager=_tool_manager(), allowed_tools=list(run.metadata.allowed_tools))
    assert report.ok, report


def test_allowlist_is_intersected_not_widened() -> None:
    """The effective allowlist is run.metadata.allowed_tools ∩ allowed_tools — never widened."""
    plan = _make_plan()
    # Run was originally accepted with a narrow allowlist that excludes "tool_b2".
    run = _run(plan, _base_refs(), status="failed", allowed=["tool_a", "tool_b", "tool_c", "tool_d"])
    delta = PlanDelta(nodes=[_valid_replacement_for_b()])  # uses "tool_b2"
    # Host policy is wider and *does* allow "tool_b2" — must not matter.
    report = validate_delta(
        delta, run=run, tool_manager=_tool_manager(), allowed_tools=["tool_a", "tool_b", "tool_b2", "tool_c", "tool_d"]
    )
    assert not report.ok
    assert "delta_tool_not_allowed" in {issue.code for issue in report.errors}
