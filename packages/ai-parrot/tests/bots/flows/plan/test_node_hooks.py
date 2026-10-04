"""FEAT-590: PlanToolNode extension hooks — inert by default, effective in a subclass."""

from __future__ import annotations

from typing import Any

import pytest

from parrot.bots.flows.plan.guards import compile_guard
from parrot.bots.flows.plan.models import ArtifactRef, ForEach, PlanNode
from parrot.bots.flows.plan.node import PlanToolNode, ToolExecutionError

from .test_node import _Ctx, _Entry, _ToolManager, _WorkingMemory


class _Escalate(ToolExecutionError):
    """A tool failure that must always be recorded, never silently dropped."""


class _EscalatingNode(PlanToolNode):
    """Test-only subclass proving the hooks are effective, not just inert.

    ``_call_with_retry`` wraps an exhausted-retries failure in a fresh
    ``ToolExecutionError`` (``raise ... from last``), so the escalation is
    recognised through the exception chain rather than by direct type —
    exactly what a real subclass dispatching through the shared retry loop
    must also do.
    """

    def _is_escalation(self, exc: BaseException) -> bool:
        return isinstance(exc, _Escalate) or isinstance(exc.__cause__, _Escalate)


def _node(plan_node: PlanNode, manager: _ToolManager, wm: _WorkingMemory, cls: Any = PlanToolNode) -> PlanToolNode:
    return cls(
        node_id=plan_node.id,
        plan_node=plan_node,
        tool_manager=manager,
        working_memory=wm,
    )


@pytest.mark.asyncio
async def test_attempt_records_dispatched_tool() -> None:
    wm, manager = _WorkingMemory(), _ToolManager({"t": {"ok": True}})
    node = _node(PlanNode(id="n", tool="t", store_as="k"), manager, wm)

    attempt = await node._call_with_retry({"a": 1})

    assert attempt.tool == "t"
    assert manager.calls == [("t", {"a": 1})]


@pytest.mark.asyncio
async def test_fanout_escalations_recorded_even_with_skip() -> None:
    wm = _WorkingMemory()
    wm._catalog._store["listing"] = _Entry({"keys": ["a.json", "b.json", "c.json"]})

    def payload(params: dict) -> dict:
        if params["key"] == "b.json":
            raise _Escalate("needs human review")
        return {"ok": True}

    manager = _ToolManager({"get": payload})
    node = _node(
        PlanNode(
            id="fetch",
            tool="get",
            args={"key": "{item}"},
            store_as="report_{index}",
            depends_on=["listing"],
            for_each=ForEach(source="{artifacts.listing}", select="keys[]", on_item_error="skip"),
        ),
        manager,
        wm,
        cls=_EscalatingNode,
    )
    ctx = _Ctx({"listing": ArtifactRef(node_id="listing", keys=["listing"])})

    ref = await node.execute(ctx)

    # on_item_error="skip" would normally drop the failure entirely; an
    # escalation must be recorded regardless.
    assert ref.escalated == 1
    assert any(e.startswith("escalate:") for e in ref.errors)
    assert ref.status == "partial"
    assert len(ref.keys) == 2


@pytest.mark.asyncio
async def test_single_escalation_returns_error_ref() -> None:
    wm, manager = _WorkingMemory(), _ToolManager({})

    def payload(_params: dict) -> None:
        raise _Escalate("needs human review")

    manager = _ToolManager({"t": payload})
    node = _node(PlanNode(id="n", tool="t", store_as="k"), manager, wm, cls=_EscalatingNode)

    ref = await node.execute(_Ctx())

    assert ref.status == "error"
    assert ref.escalated == 1
    assert any("needs human review" in e for e in ref.errors)
    assert wm.writes == []


def test_guard_extra_activation() -> None:
    guard = compile_guard("ctx.proposal.name == 'a'")
    assert guard is not None

    assert guard.evaluate({}, extra={"proposal": {"name": "a"}}) is True
    assert guard.evaluate({}, extra={"proposal": {"name": "b"}}) is False
