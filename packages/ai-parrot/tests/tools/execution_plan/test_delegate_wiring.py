"""FEAT-590 M8: delegates reach every flow path; the toolkit owns their lifecycle."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.plan import DelegatePlanNode, ExecutionPlan, PlanNode
from parrot.registry.registry import AgentRegistry
from parrot.tools.execution_plan import ExecutionPlanToolkit
from parrot.tools.execution_plan.checkpoint import build_plan_flow, plan_run_projector
from parrot.tools.execution_plan.models import PlanRun, PlanRunError
from parrot.tools.execution_plan.runs import plan_fingerprint
from parrot.tools.working_memory.tool import WorkingMemoryToolkit

from ...bots.flows.plan._delegate_fakes import FakeDelegate, FakeTool, FakeToolManager


class _Args(BaseModel):
    """Minimal schema for delegate-tool fakes."""

    query: str


def _manager() -> FakeToolManager:
    """Build the stable allowlist-scoped manager used by wiring tests."""
    return FakeToolManager(
        [FakeTool("safe", _Args), FakeTool("unsafe", _Args, delegate_safe=False)],
        {"safe": {"ok": True}, "unsafe": {"ok": True}},
    )


def _toolkit(*, delegates: list[Any] | None = None) -> ExecutionPlanToolkit:
    """Build a toolkit with live-shaped fakes and optional delegates."""
    return ExecutionPlanToolkit(
        tool_manager=_manager(),
        working_memory=WorkingMemoryToolkit(),
        allowed_tools=["safe"],
        delegates=delegates,
        delegate_trace_sink=object(),
        allow_delegate_side_effects=True,
    )


def _plan() -> ExecutionPlan:
    """Build a valid single-tool plan for factory wiring."""
    return ExecutionPlan(
        name="wiring",
        objective="verify delegate wiring",
        nodes=[PlanNode(id="run", tool="safe", store_as="run_result")],
    )


def test_build_plan_flow_registers_delegate_factory_only_with_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only configured delegates install the lazily imported delegate factory."""
    import parrot.tools.execution_plan.checkpoint as checkpoint

    captured: list[dict[str, Any]] = []

    def fake_from_definition(*_args: Any, **kwargs: Any) -> object:
        captured.append(kwargs["node_factories"])
        return object()

    monkeypatch.setattr(checkpoint.PlanFlow, "from_definition", staticmethod(fake_from_definition))
    toolkit = _toolkit()
    metadata = toolkit._new_run_metadata(_plan(), source="plan_name", run_id="run", checkpointed=False)
    bindings = dict(
        run=metadata,
        tool_manager=toolkit._tool_manager,
        working_memory=toolkit._working_memory,
        agent_registry=AgentRegistry(),
        permission_context=None,
        step_mapping={},
        store=None,
        durable_store=None,
    )

    build_plan_flow(_plan(), **bindings)
    build_plan_flow(_plan(), **bindings, delegates=(FakeDelegate([]),))

    assert list(captured[0]) == ["tool"]
    assert set(captured[1]) == {"tool", "delegate"}


def test_toolkit_threads_delegates_to_all_build_sites() -> None:
    """Fresh, resumed, and child-flow bindings share the same delegate kwargs."""
    trace_sink = object()
    toolkit = _toolkit(delegates=[FakeDelegate([])])
    toolkit._delegate_trace_sink = trace_sink

    expected = {
        "delegates": toolkit._delegates,
        "delegate_trace_sink": trace_sink,
        "allow_delegate_side_effects": True,
    }

    assert toolkit._flow_delegate_kwargs() == expected


def test_validation_receives_delegates() -> None:
    """Validation helpers retain the delegate chain and host-side policy."""
    delegate = FakeDelegate([])
    toolkit = _toolkit(delegates=[delegate])

    assert toolkit._validation_kwargs() == {
        "delegates": (delegate,),
        "allow_delegate_side_effects": True,
    }


def test_planner_rules_enabled_only_with_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delegate planner rules contain only allowlist-scoped safe tools."""
    import parrot.tools.execution_plan.toolkit as toolkit_module

    calls: list[dict[str, Any]] = []

    class FakePlanner:
        """Capture planner construction without resolving an LLM client."""

        def __init__(self, *_args: Any, **kwargs: Any) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(toolkit_module, "PlanPlanner", FakePlanner)
    _toolkit()._planner([])
    _toolkit(delegates=[FakeDelegate([], max_tools=3)])._planner([])

    assert calls == [{}, {"delegate_safe_tools": ["safe"], "delegate_max_tools": 3}]


def test_assert_policy_covers_delegate_tools() -> None:
    """Policy checking accounts for every candidate tool in a delegate node."""
    toolkit = _toolkit(delegates=[FakeDelegate([])])
    plan = ExecutionPlan(
        name="delegate-policy",
        objective="policy",
        nodes=[
            DelegatePlanNode(id="delegate", instruction="choose", tools=["safe", "unsafe"], store_as="delegate_result")
        ],
    )
    metadata = toolkit._new_run_metadata(plan, source="plan_name", run_id="run", checkpointed=False)
    metadata = metadata.model_copy(update={"allowed_tools": ["safe"], "plan_fingerprint": plan_fingerprint(plan)})
    run = PlanRun.model_construct(metadata=metadata)

    with pytest.raises(PlanRunError) as exc_info:
        toolkit._assert_policy(run)
    # PlanRunError.__str__ is the message only (models.py:317); the "policy_mismatch"
    # identifier lives on the structured .code attribute, not embedded in the text.
    assert exc_info.value.code == "policy_mismatch"


@pytest.mark.asyncio
async def test_cleanup_closes_delegates_and_tolerates_errors() -> None:
    """Cleanup closes all owned delegates even when an earlier close fails."""
    failing = FakeDelegate([])
    healthy = FakeDelegate([])

    async def fail_close() -> None:
        failing.closed = True
        raise RuntimeError("close failed")

    failing.aclose = fail_close  # type: ignore[method-assign]
    toolkit = _toolkit(delegates=[failing, healthy])

    await toolkit.cleanup()

    assert failing.closed is True
    assert healthy.closed is True


@pytest.mark.asyncio
async def test_checkpoint_holds_no_traces() -> None:
    """The checkpoint projector preserves only persisted run metadata."""
    ctx = FlowContext(initial_task="wiring", agent_registry=AgentRegistry())
    ctx.shared_data["plan_run"] = {"run_id": "run"}
    ctx.shared_data["delegate_trace"] = {"proposal": "must not persist"}

    projected = plan_run_projector(ctx)

    assert set(projected) == {"plan_run"}
    assert "delegate_trace" not in projected
