"""A2UI ``Chart`` catalog component (Module 5, FEAT-470 TASK-2539 — v1.0 lowering).

Schema vocabulary is derived from ``StructuredChartConfig``
(``parrot.models.outputs`` — FEAT-218/221) via :func:`derive_schema`
(FEAT-473 G2 — schema parity by construction): every config field is a
``CHART_SCHEMA`` property, by construction. The Pydantic class is NOT
imported into the wire format; only its field vocabulary is mirrored into
the JSON Schema.

In A2UI v1.0 the config's INPUT-ONLY ``data`` array is replaced by a data-model
binding: rows are bound via a ``{"path": "/pointer"}`` expression, resolved in
the bake pass. ECharts option-building is renderer-side (satellite) — the
lowered tree here contains only Basic Catalog primitives.
"""

from __future__ import annotations

from typing import Any

from parrot.models.outputs import StructuredChartConfig
from parrot.outputs.a2ui.catalog import register_component
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree
from parrot.outputs.a2ui.catalog.parrot._derive import derive_schema
from parrot.outputs.a2ui.models import Component

CHART_SCHEMA: dict[str, Any] = derive_schema(
    StructuredChartConfig,
    binding_fields=("data",),
    required=("type", "x", "y"),
)

CHART_INSTRUCTIONS = (
    "Use Chart to visualize numeric series over a categorical/temporal axis. "
    "Set `type` (bar/line/area/scatter/pie/donut/radar/horizontalBar/gauge/"
    "funnel/waterfall/heatmap/treemap), `x` (label column) and `y` (one or "
    "more value columns). Optional styling: `stacked`, `splitSeries` (one "
    "chart per y series), `trendline`, `showLegend`, `xAxisMode` "
    "('category'/'time'), `palette` (hex colours), `colorBySign` with "
    "`negativeColor`/`positiveColor`, `xAxisLabel`/`yAxisLabel`, `layout` "
    "('full'/'half' width hint), `mapName` (required when type='map'), "
    "`title`/`description`, and `dataVariable` (the DataFrame variable name "
    "backing the chart). Bind the row data with "
    '`data: {"path": "/pointer"}` into the data model — never inline large '
    "arrays. Display-only."
)


@register_component("Chart")
class ChartComponent:
    """The ``Chart`` catalog component (display-only, ``requires_actions=False``)."""

    SCHEMA = CHART_SCHEMA
    INSTRUCTIONS = CHART_INSTRUCTIONS

    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:
        """Lower a Chart to a Basic Catalog ``Card{child: Column}`` tree.

        A chart without a graphics backend degrades to its data summary: title,
        a type caption, an axis line, and a series list. Any data-model binding is
        passed through untouched (resolution happens in the bake pass).
        """
        props = component.model_extra or {}
        children: list[BasicNode] = []

        title = props.get("title")
        if title is not None:
            children.append(BasicNode(component="Text", text=title, metadata={"extensions": {"parrot_role": "title"}}))
        children.append(
            BasicNode(
                component="Text",
                text=f"Chart ({props.get('type', 'bar')})",
                metadata={"extensions": {"parrot_role": "caption"}},
            )
        )
        axis_text = f"x: {props.get('x', '')} | y: {', '.join(props.get('y', []) or [])}"
        children.append(BasicNode(component="Text", text=axis_text, metadata={"extensions": {"parrot_role": "axis"}}))

        x_axis_label = props.get("xAxisLabel")
        y_axis_label = props.get("yAxisLabel")
        if x_axis_label or y_axis_label:
            label_parts = []
            if x_axis_label:
                label_parts.append(f"x-axis: {x_axis_label}")
            if y_axis_label:
                label_parts.append(f"y-axis: {y_axis_label}")
            children.append(
                BasicNode(
                    component="Text",
                    text=" | ".join(label_parts),
                    metadata={"extensions": {"parrot_role": "axis-label"}},
                )
            )
        if props.get("trendline"):
            children.append(
                BasicNode(
                    component="Text",
                    text="Trendline: on",
                    metadata={"extensions": {"parrot_role": "trendline"}},
                )
            )

        series_children = [
            BasicNode(component="Text", text=name, metadata={"extensions": {"parrot_role": "series"}})
            for name in (props.get("y") or [])
        ]
        extensions: dict[str, Any] = {"parrot_role": "series-list"}
        if "data" in props:
            # Pass the binding through unresolved (under an extension key, so the
            # node still validates against the official Column schema) — the
            # bake pass resolves it.
            extensions["parrot_series_data"] = props["data"]
        series_node = BasicNode(
            component="Column",
            children=series_children,
            metadata={"extensions": extensions},
        )
        children.append(series_node)

        return BasicNode(
            id=component.id,
            component="Card",
            child=BasicNode(component="Column", children=children),
            metadata={"extensions": {"parrot_variant": "chart"}},
        )
