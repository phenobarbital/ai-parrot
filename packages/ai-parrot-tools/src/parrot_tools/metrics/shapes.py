"""KPI figures and A2UI envelopes for metric results (spec §3 M7, §7 KPICard mapping / Linked periods)."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel

from parrot.metrics.models import (
    ChartShape,
    ComparisonPolicy,
    DataTableShape,
    KPICardShape,
    MapShape,
    MetricDefinition,
    ResolvedPeriod,
    ShapeSpec,
)
from parrot.outputs.a2ui.builders import build_chart, build_datatable, build_surface
from parrot.outputs.a2ui.catalog.base import ProducerOrigin
from parrot.outputs.a2ui.catalog.parrot.kpicard import KPICARD_SCHEMA
from parrot.outputs.a2ui.linked.models import RefreshPolicy
from parrot.outputs.a2ui.models import CreateSurface
from parrot_tools.querysource import QuerysourceToolkit

logger = logging.getLogger(__name__)
_FLAT_BAND_PCT = 0.5


class KPIFigures(BaseModel):
    """Scalar KPI figures for one period plus its comparison."""

    value: Any = None
    previous: Any = None
    delta: float | None = None
    delta_pct: float | None = None
    trend: Literal["up", "down", "flat"] | None = None
    comparison_label: str | None = None
    series: list[dict[str, Any]] | None = None


def aggregate(frame_rows: Sequence[Mapping[str, Any]], shape: KPICardShape) -> Any:
    """Apply ``shape.aggregate`` to ``shape.value_column``; ``none`` requires exactly one row."""
    if not frame_rows:
        return 0 if shape.aggregate == "count" else None

    values = [row[shape.value_column] for row in frame_rows]
    if shape.aggregate == "sum":
        return sum(values)
    if shape.aggregate == "avg":
        return sum(values) / len(values)
    if shape.aggregate == "min":
        return min(values)
    if shape.aggregate == "max":
        return max(values)
    if shape.aggregate == "count":
        return len(values)
    if shape.aggregate == "first":
        return values[0]
    if shape.aggregate == "last":
        return values[-1]
    if shape.aggregate == "none":
        if len(values) != 1:
            raise ValueError("aggregate 'none' requires exactly one row")
        return values[0]
    raise ValueError(f"unsupported aggregate {shape.aggregate!r}")


def figures(
    current: Any,
    previous: Any | None,
    *,
    policy: ComparisonPolicy,
    period: ResolvedPeriod,
    comparison: ResolvedPeriod | None,
    series: list[dict] | None,
) -> KPIFigures:
    """Calculate delta, trend, and the comparison label for a KPI."""
    del period
    delta: float | None = None
    delta_pct: float | None = None
    trend: Literal["up", "down", "flat"] | None = None
    if current is not None and previous is not None:
        delta = current - previous
        if previous != 0:
            delta_pct = (delta / previous) * 100
            if abs(delta_pct) < _FLAT_BAND_PCT:
                trend = "flat"
            else:
                trend = "up" if delta_pct > 0 else "down"
        elif delta == 0:
            trend = "flat"
        else:
            trend = "up" if delta > 0 else "down"
    return KPIFigures(
        value=current,
        previous=previous,
        delta=delta,
        delta_pct=delta_pct,
        trend=trend,
        comparison_label=policy.label or (comparison.label if comparison else None),
        series=series,
    )


def kpicard_props(definition: MetricDefinition, fig: KPIFigures) -> dict[str, Any]:
    """Return schema-allowed KPICard properties with tri-state ``higherIsBetter``."""
    shape = definition.default_shape
    props: dict[str, Any] = {
        "label": definition.name,
        "value": fig.value,
        "unit": definition.unit,
        "format": definition.format,
        "delta": fig.delta_pct if definition.format != "percent" and fig.previous not in (None, 0) else fig.delta,
        "trend": fig.trend,
        "comparisonPeriod": fig.comparison_label,
        "higherIsBetter": definition.higher_is_better,
        "series": fig.series,
    }
    if isinstance(shape, KPICardShape):
        props.update({"icon": shape.icon, "color": shape.color})
    if definition.higher_is_better is True:
        props.pop("higherIsBetter")
    allowed = set(KPICARD_SCHEMA["properties"])
    return {
        key: value for key, value in props.items() if key in allowed and (value is not None or key == "higherIsBetter")
    }


def _table_columns(rows: Sequence[Mapping[str, Any]], shape: DataTableShape) -> list[dict[str, Any]]:
    """Return configured columns, deriving a minimal schema for legacy empty configuration."""
    if shape.columns:
        return list(shape.columns)
    if not rows:
        return []
    return [{"name": key, "title": key} for key in rows[0]]


def build_metric_envelope(
    definition: MetricDefinition,
    *,
    shape: ShapeSpec,
    fig: KPIFigures | None,
    rows: Sequence[Mapping[str, Any]],
    surface_id: str,
    title: str | None,
) -> CreateSurface:
    """Build a baked TOOL-origin envelope for the requested shape."""
    row_data = list(rows)
    if isinstance(shape, KPICardShape):
        if fig is None:
            raise ValueError("KPICard shape requires KPI figures")
        return build_surface(
            "KPICard", kpicard_props(definition, fig), surface_id=surface_id, origin=ProducerOrigin.TOOL
        )
    if isinstance(shape, ChartShape):
        return build_chart(
            chart_type=shape.chart_type,
            x=shape.x,
            y=shape.y,
            title=title or shape.title,
            data_binding="/rows",
            surface_id=surface_id,
            data_model={"rows": row_data},
        )
    if isinstance(shape, DataTableShape):
        return build_datatable(
            columns=_table_columns(row_data, shape),
            data_binding="/rows",
            title=title or shape.title,
            total_rows=len(row_data),
            surface_id=surface_id,
            data_model={"rows": row_data},
        )
    if isinstance(shape, MapShape):
        columns = [{"name": key, "title": key, "type": "any"} for key in row_data[0]] if row_data else []
        props = {
            "layers": [
                {
                    "layer": definition.id,
                    "columns": columns,
                    "labelField": shape.label,
                    "dataShape": "rows",
                    "totalCount": len(row_data),
                }
            ],
            "data": {"path": "/rows"},
            "title": title,
        }
        return build_surface(
            "Map", props, surface_id=surface_id, data_model={"rows": row_data}, origin=ProducerOrigin.TOOL
        )
    raise ValueError(f"unsupported shape {shape!r}")


def _linked_component(definition: MetricDefinition, shape: ShapeSpec) -> dict[str, Any]:
    """Return a Querysource-supported component definition before data binding."""
    if isinstance(shape, KPICardShape):
        props = kpicard_props(definition, KPIFigures())
        props["component"] = "KPICard"
        props["value"] = shape.value_column
        return props
    if isinstance(shape, ChartShape):
        return {"component": "Chart", "type": shape.chart_type, "x": shape.x, "y": shape.y, "title": shape.title}
    if isinstance(shape, DataTableShape):
        return {"component": "DataTable", "columns": shape.columns, "title": shape.title}
    raise ValueError(f"linked metrics do not support shape {shape.component!r}")


def _transform(source: Any) -> dict[str, Any] | None:
    """Return the documented server-side transformer descriptor when required."""
    if source.kind != "transformer":
        return None
    return {
        "python": {
            "transformer": source.transformer,
            "params": source.params,
            "input_alias": source.input_alias,
            "output": source.output,
        }
    }


def _lock_comparison_source(envelope: dict[str, Any], request: Mapping[str, Any]) -> None:
    """Mark explicit comparison placeholder values locked in a linked source descriptor."""
    source = envelope["a2ui_envelope"]["metadata"]["extensions"]["parrot_data_sources"]["previous"]
    placeholders = request.get("placeholders", {})
    for name, value in placeholders.items():
        source["conditions"][name] = value
        source["params"].setdefault(name, {"default": value, "editable": False})
        source["params"][name]["default"] = value
        source["params"][name]["editable"] = False
        if name not in source["locked"]:
            source["locked"].append(name)


async def build_linked_metric_envelope(
    querysource: QuerysourceToolkit,
    definition: MetricDefinition,
    *,
    shape: ShapeSpec,
    request: dict[str, Any],
    comparison_request: dict[str, Any] | None,
    refresh: RefreshPolicy | None,
    snapshot: bool,
    surface_id: str | None,
) -> dict[str, Any]:
    """Build a linked query-slug or transformer envelope via ``QuerysourceToolkit``."""
    source = definition.source
    if source.kind not in ("query_slug", "transformer"):
        raise ValueError(f"metric {definition.id!r}: source kind {source.kind!r} cannot be linked")
    slug_source = source if source.kind == "query_slug" else source.input
    refresh = refresh or RefreshPolicy(policy="manual")
    component = _linked_component(definition, shape)
    result = await querysource.build_linked_surface(
        slug_source.slug,
        component,
        request=request,
        tenant=slug_source.tenant,
        snapshot=snapshot,
        surface_id=surface_id,
        refresh=refresh.model_dump(),
        transform=_transform(source),
    )
    if comparison_request is None:
        return result

    comparison = await querysource.build_linked_surface(
        slug_source.slug,
        component,
        request=comparison_request,
        tenant=slug_source.tenant,
        snapshot=snapshot,
        surface_id=surface_id,
        target_key="previous",
        refresh=refresh.model_dump(),
        transform=_transform(source),
    )
    _lock_comparison_source(comparison, comparison_request)
    source_map = result["a2ui_envelope"]["metadata"]["extensions"]["parrot_data_sources"]
    previous = comparison["a2ui_envelope"]["metadata"]["extensions"]["parrot_data_sources"]["previous"]
    source_map["previous"] = previous
    return result
