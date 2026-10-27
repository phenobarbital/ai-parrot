"""Unit tests for metric shape figures and A2UI envelope builders."""

from datetime import date
from unittest.mock import AsyncMock

import pytest

from parrot.metrics.models import (
    ChartShape,
    ComparisonPolicy,
    DataTableShape,
    KPICardShape,
    MapShape,
    MetricDefinition,
    ResolvedPeriod,
)
from parrot.outputs.a2ui.catalog import validate_envelope
from parrot.outputs.a2ui.catalog.base import ProducerOrigin
from parrot.outputs.a2ui.catalog.parrot.kpicard import KPICARD_SCHEMA
from parrot_tools.metrics.shapes import (
    KPIFigures,
    aggregate,
    build_linked_metric_envelope,
    build_metric_envelope,
    figures,
    kpicard_props,
)


@pytest.fixture
def worked_hours() -> MetricDefinition:
    """Return a deterministic KPI definition with an intentionally neutral trend meaning."""
    return MetricDefinition.model_validate(
        {
            "id": "worked_hours",
            "name": "Worked Hours",
            "unit": "h",
            "format": "number",
            "higher_is_better": None,
            "time": {"binding": {"start_placeholder": "firstdate", "end_placeholder": "lastdate"}},
            "default_shape": {"component": "KPICard", "value_column": "hours"},
            "source": {"kind": "query_slug", "slug": "flex_hours", "tenant": "acme"},
        }
    )


def _period() -> ResolvedPeriod:
    """Return a fixed reporting period for figures tests."""
    return ResolvedPeriod(preset="this_month", start=date(2026, 10, 1), end=date(2026, 10, 31), label="October 2026")


def test_aggregate_all_modes_and_empty_rows() -> None:
    """All aggregate modes obey their documented empty and cardinality rules."""
    rows = [{"hours": 2}, {"hours": 3}]
    assert aggregate(rows, KPICardShape(value_column="hours", aggregate="sum")) == 5
    assert aggregate(rows, KPICardShape(value_column="hours", aggregate="avg")) == 2.5
    assert aggregate(rows, KPICardShape(value_column="hours", aggregate="min")) == 2
    assert aggregate(rows, KPICardShape(value_column="hours", aggregate="max")) == 3
    assert aggregate(rows, KPICardShape(value_column="hours", aggregate="count")) == 2
    assert aggregate(rows, KPICardShape(value_column="hours", aggregate="first")) == 2
    assert aggregate(rows, KPICardShape(value_column="hours", aggregate="last")) == 3
    assert aggregate([], KPICardShape(value_column="hours", aggregate="count")) == 0
    assert aggregate([], KPICardShape(value_column="hours", aggregate="sum")) is None
    with pytest.raises(ValueError, match="exactly one row"):
        aggregate(rows, KPICardShape(value_column="hours", aggregate="none"))


def test_figures_delta_and_trend() -> None:
    """Delta percent uses its zero guard and a sub-half-percent flat band."""
    period = _period()
    fig = figures(110, 100, policy=ComparisonPolicy(), period=period, comparison=None, series=None)
    assert fig.delta == 10 and fig.delta_pct == 10 and fig.trend == "up"
    assert figures(100.4, 100, policy=ComparisonPolicy(), period=period, comparison=None, series=None).trend == "flat"
    assert figures(5, 0, policy=ComparisonPolicy(), period=period, comparison=None, series=None).delta_pct is None


@pytest.mark.parametrize("higher_is_better, expected", [(True, "omitted"), (False, False), (None, None)])
def test_kpicard_props_schema_keys_and_tristate(
    worked_hours: MetricDefinition, higher_is_better: bool | None, expected: bool | None | str
) -> None:
    """KPICard props are schema-limited and retain the three-valued sentiment semantic."""
    definition = worked_hours.model_copy(update={"higher_is_better": higher_is_better})
    props = kpicard_props(definition, KPIFigures(value=10, previous=8, delta=2, delta_pct=25, trend="up"))
    assert set(props) <= set(KPICARD_SCHEMA["properties"])
    if expected == "omitted":
        assert "higherIsBetter" not in props
    else:
        assert props["higherIsBetter"] is expected


def test_build_metric_envelope_validates_tool_origin(worked_hours: MetricDefinition) -> None:
    """Every baked metric shape is catalog-valid for deterministic tool output."""
    rows = [{"day": "2026-10-01", "hours": 8, "lat": 40.4, "lon": -3.7, "site": "Madrid"}]
    shapes = [
        worked_hours.default_shape,
        ChartShape(x="day", y=["hours"]),
        DataTableShape(columns=[{"name": "hours", "title": "Hours", "type": "number"}]),
        MapShape(lat="lat", lon="lon", label="site"),
    ]
    for shape in shapes:
        envelope = build_metric_envelope(
            worked_hours,
            shape=shape,
            fig=KPIFigures(value=8, trend="flat"),
            rows=rows,
            surface_id=f"metric-{shape.component}",
            title=None,
        )
        validate_envelope(envelope, origin=ProducerOrigin.TOOL)


async def test_linked_uses_tenant_manual_refresh_and_locks_comparison(worked_hours: MetricDefinition) -> None:
    """Linked KPIs use the source tenant, manual default, and a locked previous source."""
    current = {
        "a2ui_envelope": {
            "metadata": {
                "extensions": {"parrot_data_sources": {"flex_hours": {"locked": [], "params": {}, "conditions": {}}}}
            }
        }
    }
    previous = {
        "a2ui_envelope": {
            "metadata": {
                "extensions": {"parrot_data_sources": {"previous": {"locked": [], "params": {}, "conditions": {}}}}
            }
        }
    }
    querysource = AsyncMock()
    querysource.build_linked_surface.side_effect = [current, previous]
    result = await build_linked_metric_envelope(
        querysource,
        worked_hours,
        shape=worked_hours.default_shape,
        request={"placeholders": {"firstdate": "FDOM", "lastdate": "LDOM"}},
        comparison_request={"placeholders": {"firstdate": "2026-09-01", "lastdate": "2026-09-30"}},
        refresh=None,
        snapshot=False,
        surface_id="metric-worked-hours",
    )
    assert querysource.build_linked_surface.call_count == 2
    assert querysource.build_linked_surface.call_args_list[0].kwargs["tenant"] == "acme"
    assert querysource.build_linked_surface.call_args_list[0].kwargs["refresh"] == {
        "policy": "manual",
        "interval_seconds": None,
    }
    assert result["a2ui_envelope"]["metadata"]["extensions"]["parrot_data_sources"]["previous"]["locked"] == [
        "firstdate",
        "lastdate",
    ]


async def test_linked_rejects_recipe(worked_hours: MetricDefinition) -> None:
    """Recipe metrics cannot be emitted as Querysource-linked surfaces."""
    payload = worked_hours.model_dump(mode="json")
    payload["source"] = {"kind": "recipe", "recipe_name": "r", "data_model_path": "/rows"}
    definition = MetricDefinition.model_validate(payload)
    with pytest.raises(ValueError, match="cannot be linked"):
        await build_linked_metric_envelope(
            AsyncMock(),
            definition,
            shape=definition.default_shape,
            request={},
            comparison_request=None,
            refresh=None,
            snapshot=False,
            surface_id=None,
        )
