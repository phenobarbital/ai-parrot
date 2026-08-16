"""Tests for the ExecutionPlan schema, selector, guards and validator."""
from __future__ import annotations

from typing import Any, List, Optional

import pytest
from pydantic import BaseModel, Field, ValidationError

from parrot.bots.flows.plan.guards import PlanGuard, compile_guard
from parrot.bots.flows.plan.models import ExecutionPlan, FacetSpec, ForEach, PlanNode
from parrot.bots.flows.plan.paths import PathError, render_key, select
from parrot.bots.flows.plan.validator import validate_plan


# ── fakes ────────────────────────────────────────────────────────────────────

class _FilterArgs(BaseModel):
    prefix: str
    limit: int = 100


class _GetArgs(BaseModel):
    key: str


class _FakeTool:
    def __init__(self, name: str, schema: type[BaseModel]) -> None:
        self.name = name
        self.args_schema = schema


class _FakeManager:
    def __init__(self, tools: dict[str, Any]) -> None:
        self._tools = tools

    def get_tool(self, tool_name: str) -> Optional[Any]:
        return self._tools.get(tool_name)

    def list_tools(self) -> List[str]:
        return list(self._tools)


@pytest.fixture
def manager() -> _FakeManager:
    return _FakeManager(
        {
            "s3_filter_reports": _FakeTool("s3_filter_reports", _FilterArgs),
            "s3_get_latest_report": _FakeTool("s3_get_latest_report", _GetArgs),
        }
    )


def _sweep_plan(**overrides: Any) -> ExecutionPlan:
    nodes = overrides.pop(
        "nodes",
        [
            PlanNode(
                id="listing",
                tool="s3_filter_reports",
                args={"prefix": "prowler/"},
                store_as="listing",
                facets=FacetSpec(counts={"n_reports": "keys[]"}),
            ),
            PlanNode(
                id="fetch",
                tool="s3_get_latest_report",
                args={"key": "{item}"},
                store_as="report_{index}",
                depends_on=["listing"],
                when="ctx.artifacts.listing.n_reports > 0",
                for_each=ForEach(source="{artifacts.listing}", select="keys[]"),
                facets=FacetSpec(group_counts={"by_severity": "findings[].severity"}),
            ),
        ],
    )
    return ExecutionPlan(
        name=overrides.pop("name", "daily_sweep"),
        objective=overrides.pop("objective", "Ingest and diff scanner reports."),
        nodes=nodes,
        **overrides,
    )


# ── paths ────────────────────────────────────────────────────────────────────

def test_select_flatten_returns_list():
    data = {"findings": [{"severity": "critical"}, {"severity": "high"}]}
    assert select(data, "findings[].severity") == ["critical", "high"]


def test_select_scalar_returns_value_not_list():
    assert select({"metadata": {"scanner": "prowler"}}, "metadata.scanner") == "prowler"


def test_select_index_picks_one_element():
    assert select({"findings": [{"id": "a"}, {"id": "b"}]}, "findings[1].id") == "b"


def test_select_missing_path_returns_default_not_raises():
    assert select({"a": 1}, "b.c", default="fallback") == "fallback"


def test_select_flatten_on_missing_key_returns_empty_list():
    assert select({"a": 1}, "findings[].id") == []


def test_malformed_path_raises():
    with pytest.raises(PathError):
        select({}, "findings[[]].id")


def test_render_key_expands_index_and_item_field():
    assert render_key("report_{index}", item={"id": "x"}, index=7) == "report_7"
    assert render_key("report_{item.id}", item={"id": "x"}, index=0) == "report_x"


def test_render_key_unresolvable_field_raises():
    with pytest.raises(PathError):
        render_key("report_{item.missing}", item={"id": "x"}, index=0)


# ── schema invariants ────────────────────────────────────────────────────────

def test_for_each_requires_varying_store_as():
    with pytest.raises(ValidationError, match="overwrite"):
        PlanNode(
            id="fetch",
            tool="t",
            store_as="constant_key",
            depends_on=["listing"],
            for_each=ForEach(source="{artifacts.listing}"),
        )


def test_item_variable_without_for_each_rejected():
    with pytest.raises(ValidationError, match="no for_each"):
        PlanNode(id="fetch", tool="t", store_as="report_{index}")


def test_for_each_source_must_be_artifact_reference():
    with pytest.raises(ValidationError, match="artifacts"):
        ForEach(source="{nodes.listing.output}")


def test_placeholder_target_must_be_declared_dependency():
    with pytest.raises(ValidationError, match="depends_on"):
        _sweep_plan(
            nodes=[
                PlanNode(id="a", tool="t", store_as="ka"),
                PlanNode(id="b", tool="t", args={"x": "{artifacts.a}"}, store_as="kb"),
            ]
        )


def test_duplicate_static_store_as_rejected():
    with pytest.raises(ValidationError, match="overwrite silently"):
        _sweep_plan(
            nodes=[
                PlanNode(id="a", tool="t", store_as="same"),
                PlanNode(id="b", tool="t", store_as="same"),
            ]
        )


def test_cycle_is_named_in_the_error():
    with pytest.raises(ValidationError, match="Dependency cycle"):
        _sweep_plan(
            nodes=[
                PlanNode(id="a", tool="t", store_as="ka", depends_on=["b"]),
                PlanNode(id="b", tool="t", store_as="kb", depends_on=["a"]),
            ]
        )


def test_self_dependency_rejected():
    with pytest.raises(ValidationError, match="cannot depend on itself"):
        PlanNode(id="a", tool="t", store_as="ka", depends_on=["a"])


def test_topological_order_is_dependency_respecting_and_stable():
    plan = _sweep_plan(
        nodes=[
            PlanNode(id="c", tool="t", store_as="kc", depends_on=["a", "b"]),
            PlanNode(id="a", tool="t", store_as="ka"),
            PlanNode(id="b", tool="t", store_as="kb", depends_on=["a"]),
        ]
    )
    order = plan.topological_order()
    assert order.index("a") < order.index("b") < order.index("c")
    assert plan.topological_order() == order


def test_referenced_nodes_finds_both_placeholder_styles():
    node = PlanNode(
        id="x",
        tool="t",
        args={"a": "{artifacts.p}", "nested": ["{nodes.q.output}"]},
        store_as="kx",
        depends_on=["p", "q"],
    )
    assert node.referenced_nodes() == {"p", "q"}


def test_plan_cannot_express_an_agent_node():
    # Recursion (agent -> tool -> flow -> agent) is impossible by type, not
    # merely forbidden by a validator: PlanNode has no agent_ref field.
    assert "agent_ref" not in PlanNode.model_fields
    with pytest.raises(ValidationError):
        PlanNode(id="a", tool="t", store_as="k", agent_ref="security_agent")


# ── validator ────────────────────────────────────────────────────────────────

def test_valid_plan_passes(manager):
    report = validate_plan(_sweep_plan(), manager)
    assert report.ok, str(report)
    assert not report.warnings


def test_unknown_tool_is_reported_with_suggestion(manager):
    plan = _sweep_plan(
        nodes=[
            PlanNode(
                id="listing",
                tool="s3_filter_report",  # typo: missing 's'
                args={"prefix": "p/"},
                store_as="listing",
            )
        ]
    )
    report = validate_plan(plan, manager)
    assert not report.ok
    issue = report.errors[0]
    assert issue.code == "unknown_tool"
    assert "s3_filter_reports" in issue.message


def test_missing_and_unknown_args_reported(manager):
    plan = _sweep_plan(
        nodes=[
            PlanNode(
                id="listing",
                tool="s3_filter_reports",
                args={"bucket": "x"},  # 'prefix' missing, 'bucket' unknown
                store_as="listing",
            )
        ]
    )
    codes = {i.code for i in validate_plan(plan, manager).errors}
    assert codes == {"missing_args", "unknown_args"}


def test_guard_referencing_unpublished_facet_is_an_error(manager):
    plan = _sweep_plan(
        nodes=[
            PlanNode(id="listing", tool="s3_filter_reports",
                     args={"prefix": "p/"}, store_as="listing"),
            PlanNode(id="fetch", tool="s3_get_latest_report",
                     args={"key": "k"}, store_as="report",
                     depends_on=["listing"],
                     when="ctx.artifacts.listing.n_reports > 0"),
        ]
    )
    issues = [i for i in validate_plan(plan, manager).errors
              if i.code == "guard_unknown_facet"]
    assert issues, "a fail-safe guard on a missing facet must not pass silently"


def test_guard_on_non_ancestor_is_an_error(manager):
    plan = _sweep_plan(
        nodes=[
            PlanNode(id="a", tool="s3_filter_reports", args={"prefix": "p/"},
                     store_as="ka", facets=FacetSpec(counts={"n": "keys[]"})),
            PlanNode(id="b", tool="s3_filter_reports", args={"prefix": "q/"},
                     store_as="kb", when="ctx.artifacts.a.n > 0"),
        ]
    )
    codes = {i.code for i in validate_plan(plan, manager).errors}
    assert "guard_not_upstream" in codes


def test_bad_guard_expression_is_reported(manager):
    plan = _sweep_plan(
        nodes=[
            PlanNode(id="listing", tool="s3_filter_reports",
                     args={"prefix": "p/"}, store_as="listing",
                     when="ctx.artifacts.listing.n >>> 0"),
        ]
    )
    codes = {i.code for i in validate_plan(plan, manager).errors}
    assert "bad_guard" in codes


def test_count_facet_without_list_marker_is_an_error(manager):
    plan = _sweep_plan(
        nodes=[
            PlanNode(id="listing", tool="s3_filter_reports",
                     args={"prefix": "p/"}, store_as="listing",
                     facets=FacetSpec(counts={"n": "keys"})),
        ]
    )
    codes = {i.code for i in validate_plan(plan, manager).errors}
    assert "count_not_a_list" in codes


def test_missing_tool_manager_is_a_warning_not_an_error():
    report = validate_plan(_sweep_plan(), None)
    assert report.ok
    assert [w.code for w in report.warnings] == ["no_tool_manager"]


def test_report_lists_every_issue_in_one_pass(manager):
    plan = _sweep_plan(
        nodes=[
            PlanNode(id="a", tool="nope", args={"x": 1}, store_as="ka",
                     facets=FacetSpec(counts={"n": "keys"})),
        ]
    )
    codes = {i.code for i in validate_plan(plan, manager).errors}
    assert {"unknown_tool", "count_not_a_list"} <= codes


# ── guards ───────────────────────────────────────────────────────────────────

def test_guard_evaluates_against_facets():
    guard = compile_guard("ctx.artifacts.listing.n_reports > 0")
    assert isinstance(guard, PlanGuard)
    assert guard.evaluate({"listing": {"n_reports": 3}}) is True
    assert guard.evaluate({"listing": {"n_reports": 0}}) is False


def test_guard_can_read_status_and_error_count():
    guard = compile_guard('ctx.status.fetch == "ok" && ctx.errors == 0')
    assert guard.evaluate({}, {"fetch": "ok"}, 0) is True
    assert guard.evaluate({}, {"fetch": "error"}, 1) is False


def test_guard_is_fail_safe_on_unknown_reference():
    # Documents the behaviour the validator exists to catch.
    guard = compile_guard("ctx.artifacts.absent.count > 0")
    assert guard.evaluate({}) is False


def test_no_guard_compiles_to_none():
    assert compile_guard(None) is None
    assert compile_guard("   ") is None


# ── compile to FlowDefinition ────────────────────────────────────────────────

def test_compiles_to_a_valid_flow_definition():
    from parrot.bots.flows.plan.compile import END_NODE_ID, PLAN_NODE_TYPE, START_NODE_ID, to_flow_definition

    fd = to_flow_definition(_sweep_plan())
    by_id = {n.id: n for n in fd.nodes}

    assert by_id[START_NODE_ID].type == "start"
    assert by_id[END_NODE_ID].type == "end"
    assert by_id["listing"].type == PLAN_NODE_TYPE
    # No agent nodes can exist: the plan schema has no agent_ref at all.
    assert all(n.agent_ref is None for n in fd.nodes)

    pairs = {(e.from_, e.to) for e in fd.edges}
    assert (START_NODE_ID, "listing") in pairs      # root wired to start
    assert ("listing", "fetch") in pairs            # depends_on -> edge
    assert ("fetch", END_NODE_ID) in pairs          # leaf wired to end


def test_compiled_edges_are_always_so_a_skipped_node_does_not_block():
    from parrot.bots.flows.plan.compile import to_flow_definition

    fd = to_flow_definition(_sweep_plan())
    assert {e.condition for e in fd.edges} == {"always"}


def test_node_config_round_trips_through_json():
    import json

    from parrot.bots.flows.plan.compile import to_flow_definition
    from parrot.bots.flows.plan.models import PlanNode

    fd = to_flow_definition(_sweep_plan())
    config = next(n for n in fd.nodes if n.id == "fetch").config
    restored = PlanNode.model_validate(json.loads(json.dumps(config)))

    assert restored.for_each is not None
    assert restored.for_each.source == "{artifacts.listing}"
    assert restored.for_each.select == "keys[]"
    assert restored.store_as == "report_{index}"
    assert restored.when == "ctx.artifacts.listing.n_reports > 0"


def test_flow_metadata_carries_plan_execution_settings():
    from parrot.bots.flows.plan.compile import to_flow_definition
    from parrot.bots.flows.plan.models import PlanMetadata

    plan = _sweep_plan(metadata=PlanMetadata(max_parallel_tasks=32, checkpoint=True))
    fd = to_flow_definition(plan)
    assert fd.metadata.max_parallel_tasks == 32
    assert fd.metadata.checkpoint is True
    # ArtifactRefs are already small; truncating them would corrupt the manifest.
    assert fd.metadata.truncation_length is None


# ── package landing (TASK-2179) ─────────────────────────────────────────────

def test_public_api_exports():
    import parrot.bots.flows.plan as plan

    for name in plan.__all__:
        assert getattr(plan, name, None) is not None


def test_tool_not_registered_on_import():
    from parrot.bots.flows.flow.flow import NODE_REGISTRY
    import parrot.bots.flows.plan  # noqa: F401

    assert "tool" not in NODE_REGISTRY
