"""FEAT-610 TASK-3846 — DashboardWidget + _build_linked_source."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from parrot_tools.querysource.models import DashboardSource, DashboardWidget
from parrot_tools.querysource.toolkit import QuerysourceToolkit


def test_dashboard_widget_defaults() -> None:
    w = DashboardWidget(key="kpi_total", slug="polestar_graduates_directory", component={"component": "KPICard"})
    assert w.request is None and w.section is None and w.tenant is None and w.refresh is None
    assert w.origin == "slug"


def test_dashboard_widget_origins() -> None:
    """Exactly one of slug | source | data; request/tenant/refresh need slug; transform needs source."""
    assert DashboardWidget(key="a", source="kpis", component={}).origin == "source"
    assert DashboardWidget(key="a", source="rows", transform={"ops": []}, component={}).origin == "source"
    assert DashboardWidget(key="a", data=[{"x": 1}], component={}).origin == "data"
    for bad in (
        {"key": "a", "component": {}},
        {"key": "a", "slug": "s", "source": "k", "component": {}},
        {"key": "a", "slug": "s", "data": [{"x": 1}], "component": {}},
        {"key": "a", "source": "k", "request": {"limit": 1}, "component": {}},
        {"key": "a", "source": "k", "tenant": "t", "component": {}},
        {"key": "a", "slug": "s", "transform": {"ops": []}, "component": {}},
        {"key": "a", "data": [], "component": {}},
        {"key": "a", "data": ["row"], "component": {}},
    ):
        with pytest.raises(ValidationError):
            DashboardWidget.model_validate(bad)


def test_dashboard_source_defaults() -> None:
    s = DashboardSource(slug="polestar_graduates_directory")
    assert s.request is None and s.tenant is None and s.refresh is None and s.transform is None


async def test_build_linked_source_target_and_conditions(patched_qs) -> None:
    toolkit = QuerysourceToolkit(dsn="postgres://fake", forced_conditions={"program": "epson"})
    detail = await toolkit.describe_slug("epson_field_activity")
    widget = DashboardWidget(
        key="activity",
        slug="epson_field_activity",
        component={"component": "Chart"},
        request={"filter": {"region": "west"}},
    )
    source = toolkit._build_linked_source(widget, detail, key=widget.key)
    assert source.target == "/activity/rows"
    assert source.slug == "epson_field_activity"
    assert source.conditions.get("program") == "epson"
    assert source.conditions["filter"] == {"region": "west"}
