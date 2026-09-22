"""FEAT-590: plan-language discriminated union."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from parrot.bots.flows.plan.models import ArtifactRef, DelegatePlanNode, ExecutionPlan, ForEach, PlanNode
from parrot.tools.execution_plan.runs import plan_fingerprint

# Computed on the pre-FEAT-590 code (step 1). NEVER recompute after the change.
_FROZEN_FINGERPRINT = "8f249908b2dd285c6da1aad02293048c25b15081045c630513a4e53d8d710ca1"

_LEGACY_PLAN = {
    "name": "legacy",
    "objective": "back-compat",
    "nodes": [
        {"id": "list", "tool": "s3_filter_reports", "args": {"prefix": "p/"}, "store_as": "listing"},
        {"id": "fetch", "tool": "s3_get", "args": {"key": "{item}"}, "store_as": "r_{index}",
         "depends_on": ["list"], "for_each": {"source": "{artifacts.list}", "select": "keys[]"}},
    ],
}


def test_plan_without_type_parses_as_tool() -> None:
    plan = ExecutionPlan.model_validate(_LEGACY_PLAN)
    assert all(isinstance(n, PlanNode) for n in plan.nodes)


def test_tool_plan_fingerprint_unchanged() -> None:
    assert plan_fingerprint(ExecutionPlan.model_validate(_LEGACY_PLAN)) == _FROZEN_FINGERPRINT


def test_delegate_node_roundtrip() -> None:
    """dump → validate keeps type='delegate' and every delegate field."""
    plan = ExecutionPlan.model_validate(
        {
            "name": "delegate-plan",
            "objective": "runtime-decided call",
            "nodes": [
                {
                    "id": "list",
                    "tool": "s3_filter_reports",
                    "args": {"prefix": "p/"},
                    "store_as": "listing",
                },
                {
                    "type": "delegate",
                    "id": "decide",
                    "instruction": "Pick the right tool for {nodes.list.output}",
                    "facts": {"n": "{nodes.list.output}"},
                    "tools": ["s3_get", "s3_head"],
                    "min_confidence": 0.5,
                    "accept_when": "ctx.proposal.confidence >= 0.5",
                    "on_reject": "escalate",
                    "allow_side_effects": True,
                    "store_as": "decision",
                    "depends_on": ["list"],
                },
            ],
        }
    )
    delegate_node = plan.node("decide")
    assert isinstance(delegate_node, DelegatePlanNode)
    dumped = plan.model_dump(mode="json")
    delegate_dump = next(n for n in dumped["nodes"] if n["id"] == "decide")
    assert delegate_dump["type"] == "delegate"

    roundtripped = ExecutionPlan.model_validate(dumped)
    roundtripped_node = roundtripped.node("decide")
    assert isinstance(roundtripped_node, DelegatePlanNode)
    assert roundtripped_node.instruction == delegate_node.instruction
    assert roundtripped_node.facts == delegate_node.facts
    assert roundtripped_node.tools == delegate_node.tools
    assert roundtripped_node.min_confidence == delegate_node.min_confidence
    assert roundtripped_node.accept_when == delegate_node.accept_when
    assert roundtripped_node.on_reject == delegate_node.on_reject
    assert roundtripped_node.allow_side_effects == delegate_node.allow_side_effects


def test_delegate_referenced_nodes_include_instruction_and_facts() -> None:
    """A {nodes.x.output} in instruction or facts without depends_on → ValueError."""
    with pytest.raises(ValidationError, match="does not list them in depends_on"):
        ExecutionPlan.model_validate(
            {
                "name": "delegate-missing-dep",
                "objective": "missing depends_on",
                "nodes": [
                    {
                        "id": "list",
                        "tool": "s3_filter_reports",
                        "args": {"prefix": "p/"},
                        "store_as": "listing",
                    },
                    {
                        "type": "delegate",
                        "id": "decide",
                        "instruction": "Use {nodes.list.output}",
                        "tools": ["s3_get"],
                        "store_as": "decision",
                        "depends_on": [],
                    },
                ],
            }
        )


def test_delegate_store_as_for_each_rules() -> None:
    """Inherited rule: for_each requires a per-item store_as key."""
    with pytest.raises(ValidationError, match="fans out with for_each"):
        DelegatePlanNode(
            id="decide",
            instruction="Pick a tool for {item}",
            tools=["s3_get"],
            store_as="decision",
            for_each=ForEach(source="{artifacts.list}"),
        )


def test_tool_names() -> None:
    tool_node = PlanNode(id="fetch", tool="s3_get", store_as="r")
    assert tool_node.tool_names() == frozenset({"s3_get"})

    delegate_node = DelegatePlanNode(
        id="decide",
        instruction="pick",
        tools=["s3_get", "s3_head"],
        store_as="decision",
    )
    assert delegate_node.tool_names() == frozenset({"s3_get", "s3_head"})


def test_artifact_ref_escalated_default() -> None:
    assert ArtifactRef(node_id="x").escalated == 0
