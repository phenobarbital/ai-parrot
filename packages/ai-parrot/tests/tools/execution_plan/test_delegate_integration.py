"""FEAT-590: end-to-end delegate plans and tool-only resume compatibility."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from parrot.bots.flows.plan.delegate import ToolCallProposal
from parrot.bots.flows.plan.models import DelegatePlanNode, ExecutionPlan, ForEach, PlanNode
from parrot.tools.execution_plan import ExecutionPlanToolkit
from parrot.tools.execution_plan.models import PlanDelta, PlanRun
from parrot.tools.execution_plan.repair import validate_delta
from parrot.tools.execution_plan.runs import plan_fingerprint
from parrot.tools.working_memory.tool import WorkingMemoryToolkit

from ...bots.flows.plan._delegate_fakes import FakeDelegate, FakeTool, FakeToolManager
from ._recovery_fakes import ScriptedPlannerClient

_FROZEN_TOOL_ONLY_FINGERPRINT = "8f249908b2dd285c6da1aad02293048c25b15081045c630513a4e53d8d710ca1"


class _EmptyArgs(BaseModel):
    """Schema for no-argument fake tools."""


class _UrlArgs(BaseModel):
    """Schema for delegate-selected URL operations."""

    url: str


class _TraceSink:
    """Collect trace records without persisting them in test checkpoints."""

    def __init__(self) -> None:
        self.records: list[Any] = []

    async def record(self, trace: Any) -> None:
        """Retain a delegate trace."""
        self.records.append(trace)


def _proposal(name: str | None, arguments: dict[str, Any] | None = None) -> ToolCallProposal:
    """Build one fake delegate proposal."""
    return ToolCallProposal(
        name=name,
        arguments=arguments or {},
        confidence=0.9,
        backend="fake",
        latency_ms=1.0,
    )


def _plan() -> ExecutionPlan:
    """Build the tool-to-delegate triage plan exercised end to end."""
    return ExecutionPlan(
        name="delegate-triage",
        objective="Load rows and triage each one.",
        nodes=[
            PlanNode(id="load_rows", tool="load_rows", store_as="loaded_rows"),
            DelegatePlanNode(
                id="triage",
                instruction="Triage {item}.",
                tools=["retry_with_proxy", "mark_unavailable"],
                on_reject="escalate",
                store_as="triage_{index}",
                depends_on=["load_rows"],
                for_each=ForEach(source="{artifacts.load_rows}", select="rows[]"),
            ),
        ],
    )


@pytest.mark.asyncio
async def test_plan_with_delegate_fan_out_end_to_end() -> None:
    """Accepted proposals dispatch, while declined proposals escalate safely."""
    trace_sink = _TraceSink()
    manager = FakeToolManager(
        [
            FakeTool("load_rows", _EmptyArgs),
            FakeTool("retry_with_proxy", _UrlArgs),
            FakeTool("mark_unavailable", _UrlArgs),
        ],
        {
            "load_rows": {"rows": ["https://one.example", "https://two.example", "secret-payload-row"]},
            "retry_with_proxy": {"retried": True},
            "mark_unavailable": {"marked": True},
        },
    )
    delegate = FakeDelegate(
        [
            _proposal("retry_with_proxy", {"url": "https://one.example"}),
            _proposal(None),
            _proposal("mark_unavailable", {"url": "secret-payload-row"}),
        ]
    )
    toolkit = ExecutionPlanToolkit(
        tool_manager=manager,
        working_memory=WorkingMemoryToolkit(),
        delegates=[delegate],
        delegate_trace_sink=trace_sink,
        allow_delegate_side_effects=False,
    )

    result = await toolkit._run_plan(_plan(), source="plan_name")

    assert result.status == "success"
    triage_ref = next(ref for ref in result.result["artifacts"] if ref["node_id"] == "triage")
    assert triage_ref["status"] == "partial"
    assert triage_ref["escalated"] == 1
    assert [call for call in manager.calls if call[0] != "load_rows"] == [
        ("retry_with_proxy", {"url": "https://one.example"}),
        ("mark_unavailable", {"url": "secret-payload-row"}),
    ]
    assert "secret-payload-row" not in str(result.result)
    assert len(trace_sink.records) == 3


@pytest.mark.asyncio
async def test_checkpointed_tool_plan_resumes_after_upgrade() -> None:
    """A frozen pre-delegate fingerprint remains acceptable to resume policy."""
    legacy_plan = ExecutionPlan.model_validate(
        {
            "name": "legacy",
            "objective": "back-compat",
            "nodes": [
                {
                    "id": "list",
                    "tool": "s3_filter_reports",
                    "args": {"prefix": "p/"},
                    "store_as": "listing",
                },
                {
                    "id": "fetch",
                    "tool": "s3_get",
                    "args": {"key": "{item}"},
                    "store_as": "r_{index}",
                    "depends_on": ["list"],
                    "for_each": {"source": "{artifacts.list}", "select": "keys[]"},
                },
            ],
        }
    )
    assert plan_fingerprint(legacy_plan) == _FROZEN_TOOL_ONLY_FINGERPRINT
    manager = FakeToolManager(
        [FakeTool("s3_filter_reports", _EmptyArgs), FakeTool("s3_get", _UrlArgs)],
        {"s3_filter_reports": {"keys": []}, "s3_get": {"ok": True}},
    )
    toolkit = ExecutionPlanToolkit(tool_manager=manager, working_memory=WorkingMemoryToolkit())
    metadata = toolkit._new_run_metadata(legacy_plan, source="plan_name", run_id="legacy", checkpointed=False)
    run = PlanRun.model_construct(
        metadata=metadata.model_copy(update={"plan_fingerprint": _FROZEN_TOOL_ONLY_FINGERPRINT})
    )

    toolkit._assert_policy(run)


@pytest.mark.asyncio
async def test_mixed_plan_repair_targets_tool_node() -> None:
    """A failed tool is repaired in a mixed plan, but a delegate is never a delta target."""

    def fail(_: dict[str, Any]) -> None:
        raise RuntimeError("broken")

    plan = ExecutionPlan(
        name="mixed-repair",
        objective="Repair the failed tool before delegate triage.",
        nodes=[
            PlanNode(id="load", tool="broken", store_as="loaded"),
            DelegatePlanNode(
                id="triage",
                instruction="Choose a follow-up.",
                tools=["retry_with_proxy"],
                store_as="triaged",
                depends_on=["load"],
            ),
        ],
    )
    manager = FakeToolManager(
        [
            FakeTool("broken", _EmptyArgs),
            FakeTool("fixed", _EmptyArgs),
            FakeTool("retry_with_proxy", _UrlArgs),
        ],
        {"broken": fail, "fixed": {"loaded": True}, "retry_with_proxy": {"retried": True}},
    )
    delta = PlanDelta(nodes=[PlanNode(id="load", tool="fixed", store_as="loaded")])
    toolkit = ExecutionPlanToolkit(
        tool_manager=manager,
        working_memory=WorkingMemoryToolkit(),
        delegates=[FakeDelegate([_proposal("retry_with_proxy", {"url": "https://fixed.example"})])],
        planner_llm=ScriptedPlannerClient([delta.model_dump_json()]),
    )

    original = await toolkit._run_plan(plan, source="plan_name")
    repaired = await toolkit.plan_repair(original.result["run_id"])

    assert original.result["status"] == "partial"
    assert repaired.status == "success"
    assert repaired.result["status"] == "completed"
    assert manager.calls == [
        ("broken", {}),
        ("fixed", {}),
        ("retry_with_proxy", {"url": "https://fixed.example"}),
    ]
    run = await toolkit._resolver.resolve(original.result["run_id"])
    rejected = validate_delta(
        PlanDelta(nodes=[PlanNode(id="triage", tool="fixed", store_as="triaged", depends_on=["load"])]),
        run=run,
        tool_manager=manager,
        allowed_tools=manager.list_tools(),
        delegates=toolkit._delegates,
    )
    assert "delta_delegate_not_repairable" in {issue.code for issue in rejected.errors}
