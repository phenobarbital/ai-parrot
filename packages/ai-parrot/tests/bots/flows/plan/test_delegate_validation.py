"""FEAT-590 M4: delegate validator rules and compiler."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from parrot.bots.flows.core.node import Node
from parrot.bots.flows.flow.flow import NODE_REGISTRY
from parrot.bots.flows.plan import (
    DELEGATE_NODE_TYPE,
    ensure_delegate_node_registered,
    to_flow_definition,
    validate_plan,
)
from parrot.bots.flows.plan.models import DelegatePlanNode, ExecutionPlan, PlanNode

from ._delegate_fakes import FakeDelegate, FakeTool, FakeToolManager


class _UrlArgs(BaseModel):
    """Arguments for the fake URL tool."""

    url: str


def _plan(**delegate_kw: object) -> ExecutionPlan:
    """Build a plan with an upstream tool and a delegate node."""
    defaults: dict[str, object] = {
        "id": "pick",
        "instruction": "Choose a URL tool for the source result.",
        "tools": ["fetch_url"],
        "store_as": "picked",
        "depends_on": ["src"],
    }
    defaults.update(delegate_kw)
    return ExecutionPlan(
        name="delegate-validation",
        objective="Validate a delegate node.",
        nodes=[
            PlanNode(id="src", tool="source", args={"url": "https://example.test"}, store_as="source"),
            DelegatePlanNode(**defaults),
        ],
    )


def _manager(*, delegate_safe: bool = True) -> FakeToolManager:
    """Return a manager containing the source and URL tools."""
    return FakeToolManager(
        [
            FakeTool("source", _UrlArgs),
            FakeTool("fetch_url", _UrlArgs, delegate_safe=delegate_safe),
        ],
        {},
    )


@pytest.mark.parametrize(
    "code",
    [
        "unknown_tool",
        "duplicate_delegate_tools",
        "no_delegate_configured",
        "too_many_delegate_tools",
        "delegate_side_effect",
        "bad_accept_when",
    ],
)
def test_validator_delegate_rules(code: str) -> None:
    """Each delegate-specific validation rule is reported."""
    manager = _manager(delegate_safe=code != "delegate_side_effect")
    plan_kwargs: dict[str, object] = {}
    delegates: list[FakeDelegate] | None = [FakeDelegate([])]

    if code == "unknown_tool":
        plan_kwargs["tools"] = ["fetch_urll"]
    elif code == "duplicate_delegate_tools":
        plan_kwargs["tools"] = ["fetch_url", "fetch_url"]
    elif code == "no_delegate_configured":
        delegates = None
    elif code == "too_many_delegate_tools":
        plan_kwargs["tools"] = ["fetch_url", "source"]
        delegates = [FakeDelegate([], max_tools=1)]
    elif code == "bad_accept_when":
        plan_kwargs["accept_when"] = "ctx.proposal.name >>> 0"

    report = validate_plan(_plan(**plan_kwargs), manager, delegates=delegates)
    assert code in {issue.code for issue in report.issues}


def test_side_effects_need_node_and_host() -> None:
    """An unsafe tool needs both the node and host policy switches."""
    manager = _manager(delegate_safe=False)
    delegates = [FakeDelegate([])]

    no_node_flag = validate_plan(_plan(), manager, delegates=delegates, allow_delegate_side_effects=True)
    no_host_flag = validate_plan(
        _plan(allow_side_effects=True),
        manager,
        delegates=delegates,
        allow_delegate_side_effects=False,
    )
    both_flags = validate_plan(
        _plan(allow_side_effects=True),
        manager,
        delegates=delegates,
        allow_delegate_side_effects=True,
    )

    assert "delegate_side_effect" in {issue.code for issue in no_node_flag.errors}
    assert "delegate_side_effect" in {issue.code for issue in no_host_flag.errors}
    assert "delegate_side_effect" not in {issue.code for issue in both_flags.errors}


def test_tool_only_plan_report_unchanged() -> None:
    """Delegate kwargs leave tool-only plan validation unchanged."""
    plan = ExecutionPlan(
        name="tool-only",
        objective="Preserve existing validation.",
        nodes=[PlanNode(id="only", tool="missing", store_as="result")],
    )
    manager = _manager()

    legacy = validate_plan(plan, manager)
    with_delegate_kwargs = validate_plan(
        plan,
        manager,
        delegates=[FakeDelegate([])],
        allow_delegate_side_effects=True,
    )

    assert with_delegate_kwargs.issues == legacy.issues


def test_compile_emits_delegate_type() -> None:
    """Delegate nodes compile with delegate-specific type, label, and metadata."""
    definition = to_flow_definition(_plan(tools=["source", "fetch_url"]))
    node = next(item for item in definition.nodes if item.id == "pick")

    assert node.type == DELEGATE_NODE_TYPE
    assert node.label == "delegate:fetch_url|source"
    assert node.metadata == {"plan": "delegate-validation", "tools": ["fetch_url", "source"]}


def test_ensure_delegate_node_registered_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delegate registration is idempotent and rejects a foreign owner."""

    class DelegateNode(Node):
        """Minimal node class used only for registry testing."""

    class ForeignDelegateNode(Node):
        """Distinct node class used to prove registry ownership checks."""

    monkeypatch.delitem(NODE_REGISTRY, DELEGATE_NODE_TYPE, raising=False)
    ensure_delegate_node_registered(DelegateNode)
    ensure_delegate_node_registered(DelegateNode)
    assert NODE_REGISTRY[DELEGATE_NODE_TYPE] is DelegateNode
    with pytest.raises(ValueError, match="already"):
        ensure_delegate_node_registered(ForeignDelegateNode)
