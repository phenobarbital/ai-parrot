"""FEAT-610 TASK-3846 — DashboardWidget + _build_linked_source."""

from __future__ import annotations

from parrot_tools.querysource.models import DashboardWidget
from parrot_tools.querysource.toolkit import QuerysourceToolkit


def test_dashboard_widget_defaults() -> None:
    w = DashboardWidget(key="kpi_total", slug="polestar_graduates_directory", component={"component": "KPICard"})
    assert w.request is None and w.section is None and w.tenant is None and w.refresh is None


async def test_build_linked_source_target_and_conditions(patched_qs) -> None:
    toolkit = QuerysourceToolkit(dsn="postgres://fake", forced_conditions={"program": "epson"})
    detail = await toolkit.describe_slug("epson_field_activity")
    widget = DashboardWidget(
        key="activity",
        slug="epson_field_activity",
        component={"component": "Chart"},
        request={"filter": {"region": "west"}},
    )
    source = toolkit._build_linked_source(widget, detail)
    assert source.target == "/activity/rows"
    assert source.slug == "epson_field_activity"
    assert source.conditions.get("program") == "epson"
    assert source.conditions["filter"] == {"region": "west"}
