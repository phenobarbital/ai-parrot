"""Tests for pure linked-widget materialization helpers (FEAT-757)."""
from __future__ import annotations

from typing import Any

from parrot.memory.compaction.models import ToolInvocation, ToolStatus
from parrot.outputs.a2ui.linked.materialize import component_from_envelope, extract_slug_origin


def _exec(slug: str = "flex_hours_query_pbi", **extra: Any) -> ToolInvocation:
    """Build a completed query-source slug execution."""
    return ToolInvocation(tool_name="qs_execute_slug", input={"slug": slug, **extra})


def test_extract_origin_last_completed_wins() -> None:
    """Repeated executions of one origin resolve to the final invocation."""
    outcome = extract_slug_origin([_exec(limit=10), _exec(limit=10)])

    assert outcome.kind == "slug"
    assert outcome.origin is not None
    assert outcome.origin.request == {"limit": 10}


def test_extract_origin_ignores_errored() -> None:
    """An errored invocation cannot replace a completed origin."""
    outcome = extract_slug_origin([
        _exec(),
        ToolInvocation(tool_name="qs_execute_slug", input={"slug": "other"}, status=ToolStatus.ERROR),
    ])

    assert outcome.kind == "slug"
    assert outcome.origin is not None
    assert outcome.origin.slug == "flex_hours_query_pbi"


def test_extract_origin_already_linked() -> None:
    """A trailing linked-surface build marks the turn as already linked."""
    outcome = extract_slug_origin([_exec(), ToolInvocation(tool_name="qs_build_linked_surface", input={})])

    assert outcome.kind == "already_linked"
    assert outcome.origin is None


def test_extract_origin_multi_source() -> None:
    """Distinct query origins cannot be represented by one linked widget."""
    outcome = extract_slug_origin([_exec("hours"), _exec("expenses")])

    assert outcome.kind == "multi_source"
    assert outcome.origin is None


def test_extract_origin_none() -> None:
    """A turn without query-source executions has no materializable origin."""
    assert extract_slug_origin([]).kind == "none"
    assert extract_slug_origin([ToolInvocation(tool_name="python_repl", input={})]).kind == "none"


def test_extract_origin_neutral_tools_tolerated() -> None:
    """Read-only query and skill tools do not invalidate an origin."""
    outcome = extract_slug_origin([
        ToolInvocation(tool_name="qs_describe_slug", input={"slug": "flex_hours_query_pbi"}),
        _exec(),
        ToolInvocation(tool_name="load_skill", input={"name": "reporting"}),
    ])

    assert outcome.kind == "slug"


def test_extract_origin_non_neutral_tool_blocks() -> None:
    """A transform outside the closed neutral-tool set invalidates the origin."""
    outcome = extract_slug_origin([_exec(), ToolInvocation(tool_name="python_repl", input={})])

    assert outcome.kind == "none"


def test_extract_origin_offloaded_input_is_none() -> None:
    """An offloaded query input cannot safely be reconstructed."""
    outcome = extract_slug_origin([ToolInvocation(tool_name="qs_execute_slug", input={}, omitted={"input": "om_x"})])

    assert outcome.kind == "none"


def test_extract_origin_drops_offset_keeps_tenant() -> None:
    """Paging and refresh flags are omitted while tenant identity is retained."""
    outcome = extract_slug_origin([_exec(tenant="acme", offset=20, refresh=True, limit=10)])

    assert outcome.kind == "slug"
    assert outcome.origin is not None
    assert outcome.origin.tenant == "acme"
    assert outcome.origin.request == {"limit": 10}


def test_component_strips_bindings_and_rows() -> None:
    """Supported root components keep display properties but lose baked bindings."""
    chart = component_from_envelope({"components": [
        {"id": "root", "component": "Chart", "data": {"path": "/hours/rows"}, "x": "month", "y": "total"}
    ]})
    table = component_from_envelope({"components": [
        {"id": "root", "component": "DataTable", "data": {"path": "/hours/rows"}, "columns": ["total"]}
    ]})
    kpi = component_from_envelope({"components": [
        {"id": "root", "component": "KPICard", "label": "Hours", "value": {"path": "/hours/rows/0/total"}}
    ]})

    assert chart == {"id": "root", "component": "Chart", "x": "month", "y": "total"}
    assert table == {"id": "root", "component": "DataTable", "columns": ["total"]}
    assert kpi == {"id": "root", "component": "KPICard", "label": "Hours", "value": "total"}


def test_component_kpicard_literal_value_unsupported() -> None:
    """A literal KPI value has no source column to bind."""
    component = component_from_envelope({"components": [{"component": "KPICard", "value": 42}]})

    assert component is None


def test_component_unsupported_root() -> None:
    """Unsupported root components cannot be rebuilt by the query-source toolkit."""
    component = component_from_envelope({"components": [{"component": "Infographic"}]})

    assert component is None


def test_component_wrapped_envelope() -> None:
    """A serialized createSurface wrapper is unwrapped before root selection."""
    component = component_from_envelope({"createSurface": {
        "components": [{"component": "DataTable", "data": {"path": "/hours/rows"}, "columns": ["date"]}]
    }})

    assert component == {"component": "DataTable", "columns": ["date"]}
