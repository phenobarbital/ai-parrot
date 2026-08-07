"""Unit tests for the tool catalog + allowlist validation layering
(TASK-2182).
"""
from __future__ import annotations

from typing import Any, List, Optional

import pytest
from pydantic import BaseModel, Field

from parrot.bots.flows.plan import ExecutionPlan, PlanNode
from parrot.tools.execution_plan.catalog import (
    ToolCatalogEntry,
    build_catalog,
    check_allowlist,
    validate_with_allowlist,
)


class _FilterArgs(BaseModel):
    prefix: str = Field(..., description="S3 key prefix to filter on, quite a long one indeed")
    limit: int = 100


class _FakeTool:
    def __init__(self, name: str, description: str, args_schema: Optional[type] = None) -> None:
        self.name = name
        self.description = description
        self.args_schema = args_schema


class _FakeToolManager:
    def __init__(self, tools: dict) -> None:
        self._tools = tools

    def get_tool(self, name: str) -> Optional[Any]:
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        return list(self._tools)


@pytest.fixture
def manager() -> _FakeToolManager:
    return _FakeToolManager(
        {
            "s3_filter_reports": _FakeTool(
                "s3_filter_reports", "Filter S3 report objects", _FilterArgs
            ),
            "s3_get_latest_report": _FakeTool("s3_get_latest_report", "Fetch one report"),
            "delete_everything": _FakeTool("delete_everything", "Dangerous — not allowlisted"),
        }
    )


def _sweep_plan(**overrides: Any) -> ExecutionPlan:
    nodes = overrides.pop(
        "nodes",
        [
            PlanNode(
                id="listing", tool="s3_filter_reports",
                args={"prefix": "prowler/"}, store_as="listing",
            ),
        ],
    )
    return ExecutionPlan(
        name=overrides.pop("name", "sweep"),
        objective=overrides.pop("objective", "test plan"),
        nodes=nodes,
        **overrides,
    )


class TestBuildCatalog:
    def test_none_allowlist_is_all_tools(self, manager: _FakeToolManager) -> None:
        catalog = build_catalog(manager, None)
        assert [entry.name for entry in catalog] == list(manager.list_tools())

    def test_subset_intersection(self, manager: _FakeToolManager) -> None:
        catalog = build_catalog(manager, ["s3_get_latest_report", "s3_filter_reports"])
        # Order-stable relative to tool_manager.list_tools(), not allowlist order.
        assert [entry.name for entry in catalog] == ["s3_filter_reports", "s3_get_latest_report"]

    def test_unregistered_allowlisted_name_raises(self, manager: _FakeToolManager) -> None:
        with pytest.raises(ValueError, match="not_a_real_tool"):
            build_catalog(manager, ["s3_filter_reports", "not_a_real_tool"])

    def test_args_summary_bounded(self, manager: _FakeToolManager) -> None:
        catalog = build_catalog(manager, ["s3_filter_reports"])
        entry = catalog[0]
        assert isinstance(entry, ToolCatalogEntry)
        names = {arg.name for arg in entry.args_summary}
        assert names == {"prefix", "limit"}
        prefix_arg = next(a for a in entry.args_summary if a.name == "prefix")
        assert prefix_arg.required is True
        assert len(prefix_arg.description) <= 120
        limit_arg = next(a for a in entry.args_summary if a.name == "limit")
        assert limit_arg.required is False

    def test_args_summary_empty_for_untyped_tool(self, manager: _FakeToolManager) -> None:
        catalog = build_catalog(manager, ["s3_get_latest_report"])
        assert catalog[0].args_summary == []


class TestAllowlistValidation:
    def test_tool_not_allowed_issue(self, manager: _FakeToolManager) -> None:
        plan = _sweep_plan(
            nodes=[
                PlanNode(
                    id="wipe", tool="delete_everything", store_as="wipe_result",
                ),
            ],
        )
        issues = check_allowlist(plan, ["s3_filter_reports", "s3_get_latest_report"])
        assert len(issues) == 1
        assert issues[0].code == "tool_not_allowed"
        assert issues[0].node_id == "wipe"

    def test_allowlist_none_means_no_allowlist_issues(self) -> None:
        plan = _sweep_plan(
            nodes=[PlanNode(id="wipe", tool="delete_everything", store_as="k")],
        )
        assert check_allowlist(plan, None) == []

    def test_combined_report_single_pass(self, manager: _FakeToolManager) -> None:
        plan = _sweep_plan(
            nodes=[
                # Unknown tool AND not on the allowlist — two independent
                # issues, both in the same report.
                PlanNode(id="bad", tool="totally_unregistered", store_as="k"),
            ],
        )
        report = validate_with_allowlist(
            plan, manager, allowed_tools=["s3_filter_reports"],
        )
        codes = {issue.code for issue in report.errors}
        assert codes == {"unknown_tool", "tool_not_allowed"}
        assert report.ok is False

    def test_allowlist_none_passes_everything_registered(self, manager: _FakeToolManager) -> None:
        plan = _sweep_plan(
            nodes=[PlanNode(id="listing", tool="s3_filter_reports",
                             args={"prefix": "p/"}, store_as="listing")],
        )
        report = validate_with_allowlist(plan, manager, allowed_tools=None)
        assert report.ok

    def test_registered_but_not_allowlisted_fails_pre_execution(
        self, manager: _FakeToolManager
    ) -> None:
        plan = _sweep_plan(
            nodes=[PlanNode(id="wipe", tool="delete_everything", store_as="k")],
        )
        report = validate_with_allowlist(
            plan, manager, allowed_tools=["s3_filter_reports"],
        )
        assert not report.ok
        assert any(issue.code == "tool_not_allowed" for issue in report.errors)
