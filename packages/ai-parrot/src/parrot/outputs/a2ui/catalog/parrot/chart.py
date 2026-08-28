"""A2UI ``Chart`` catalog component (Module 3).

Schema vocabulary is adapted from ``StructuredChartConfig``
(``parrot.models.outputs`` — FEAT-218/221): ``type``, ``x``, ``y``, ``stacked``,
``showLegend``, ``xAxisMode``, ``palette``. The Pydantic class is NOT imported into
the wire format; only its field vocabulary is mirrored into the JSON Schema.

In A2UI the config's INPUT-ONLY ``data`` array is replaced by a data-model binding:
rows are bound via a ``{"$bind": "/pointer"}`` expression, resolved in the Module 6
bake pass. ECharts option-building is renderer-side (satellite) — the lowered tree
here contains only Basic Catalog primitives.
"""

from __future__ import annotations

from typing import Any

from parrot.outputs.a2ui.catalog import register_component
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree
from parrot.outputs.a2ui.models import Component

CHART_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "type": {
            "type": "string",
            "enum": ["bar", "line", "area", "scatter", "pie", "map"],
            "description": "Chart type (StructuredChartConfig.type vocabulary).",
        },
        "x": {"type": "string", "description": "Categorical/label column name."},
        "y": {
            "type": "array",
            "items": {"type": "string"},
            "description": "One or more value column names (multi-series).",
        },
        "stacked": {"type": "boolean", "default": False},
        "showLegend": {"type": "boolean", "default": True},
        "xAxisMode": {"type": "string"},
        "palette": {"type": "array", "items": {"type": "string"}},
        "data": {
            "description": "Data-model binding ({'$bind': '/pointer'}) to the row set.",
        },
    },
    "required": ["type", "x", "y"],
}

CHART_INSTRUCTIONS = (
    "Use Chart to visualize numeric series over a categorical/temporal axis. "
    "Set `type` (bar/line/area/scatter/pie), `x` (label column) and `y` (one or "
    "more value columns). Bind the row data with `data: {\"$bind\": \"/pointer\"}` "
    "into the data model — never inline large arrays. Display-only."
)


@register_component("Chart")
class ChartComponent:
    """The ``Chart`` catalog component (display-only, ``requires_actions=False``)."""

    SCHEMA = CHART_SCHEMA
    INSTRUCTIONS = CHART_INSTRUCTIONS

    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:
        """Lower a Chart to a Basic Catalog tree (pure, deterministic).

        A chart without a graphics backend degrades to its data summary: title,
        a type caption, an axis line, and a series list. Any data-model binding is
        passed through untouched (resolution happens in the bake pass).
        """
        props = component.properties
        children: list[BasicNode] = []

        title = props.get("title")
        if title is not None:
            children.append(
                BasicNode(component="Text", properties={"role": "title", "text": title})
            )
        children.append(
            BasicNode(
                component="Text",
                properties={"role": "caption", "text": f"Chart ({props.get('type', 'bar')})"},
            )
        )
        axis_text = f"x: {props.get('x', '')} | y: {', '.join(props.get('y', []) or [])}"
        children.append(
            BasicNode(component="Text", properties={"role": "axis", "text": axis_text})
        )

        series_children = [
            BasicNode(component="Text", properties={"role": "series", "text": name})
            for name in (props.get("y") or [])
        ]
        series_props: dict[str, Any] = {"role": "series-list"}
        if "data" in props:
            # Pass the binding through unresolved — the bake pass will resolve it.
            series_props["data"] = props["data"]
        children.append(
            BasicNode(component="Column", properties=series_props, children=series_children)
        )

        return BasicNode(
            component="Card",
            properties={"variant": "chart", "componentId": component.id},
            children=children,
        )
