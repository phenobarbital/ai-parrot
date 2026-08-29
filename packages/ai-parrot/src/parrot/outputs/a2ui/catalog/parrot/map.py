"""A2UI ``Map`` catalog component (Module 5, FEAT-470 TASK-2539 — v1.0 lowering).

Schema vocabulary is derived from ``StructuredMapConfig``/``MapLayer``/
``MapViewport``/``MapQuery`` (``parrot.models.outputs``) via
:func:`derive_schema` (FEAT-473 G2): ``layers`` (full ``MapLayer`` vocabulary —
``layer``, ``columns``, ``tooltipTemplate``, ``labelField``, ``dataShape``,
``totalCount``, ``capped``, ``geodesic``, ``markerColor``), ``viewport``,
``query``, ``baseLayer``, ``title``, ``description``. The INPUT-ONLY ``data``/
``datasets`` arrays are replaced by data-model bindings.

``lower()`` degrades a Map to a static-friendly Basic tree (title/description Text
plus a layer-summary Column). Interactive tiles are the folium-map renderer's native
path (Module 7, satellite) — no geo/folium markup appears in the lowered tree.
"""

from __future__ import annotations

from typing import Any

from parrot.models.outputs import StructuredMapConfig
from parrot.outputs.a2ui.catalog import register_component
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree
from parrot.outputs.a2ui.catalog.parrot._derive import derive_schema
from parrot.outputs.a2ui.models import Component

MAP_SCHEMA: dict[str, Any] = derive_schema(
    StructuredMapConfig,
    binding_fields=("data", "datasets"),
    required=("layers",),
)

MAP_INSTRUCTIONS = (
    "Use Map for geospatial data. Declare `layers`, each a full MapLayer: `layer` "
    "(source id), `columns` (name/type/title/format), optional `tooltipTemplate` "
    "(str.format_map template over feature properties), `labelField` (marker label "
    "property key), `dataShape` ('geojson'/'rows'), `totalCount`/`capped` (true "
    "count vs. truncation), `geodesic` (path type) and `markerColor`. Optional "
    "`viewport` (bbox/center/zoom), `query` (echoed spatial filter: point/radius/"
    "unit), `baseLayer`, `title`, `description`. Bind features with "
    '`data: {"path": "/pointer"}` (per-layer geo features); `datasets` is '
    "input-only and never appears on the wire. On static surfaces the map "
    "degrades to a titled layer summary. Display-only."
)


def _layer_summary_text(layer: dict[str, Any]) -> str:
    """Build a titled one-line summary for a single ``MapLayer`` dict.

    Args:
        layer: A ``MapLayer``-shaped dict (camelCase props: ``layer``,
            ``labelField``, ``markerColor``, ``totalCount``, ``capped``, ...).

    Returns:
        A ``" | "``-joined summary: layer id, then any of
        ``labelField``/``markerColor``/``totalCount``/``capped`` that are set.
    """
    parts = [str(layer.get("layer", ""))]
    label_field = layer.get("labelField")
    if label_field:
        parts.append(f"label={label_field}")
    marker_color = layer.get("markerColor")
    if marker_color:
        parts.append(f"color={marker_color}")
    if "totalCount" in layer:
        parts.append(f"total={layer['totalCount']}")
    if layer.get("capped"):
        parts.append("capped")
    return " | ".join(parts)


@register_component("Map")
class MapComponent:
    """The ``Map`` catalog component (display-only, ``requires_actions=False``)."""

    SCHEMA = MAP_SCHEMA
    INSTRUCTIONS = MAP_INSTRUCTIONS

    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:
        """Lower a Map to a static-friendly Basic Catalog ``Card{child: Column}`` tree."""
        props = component.model_extra or {}
        children: list[BasicNode] = []

        title = props.get("title")
        if title is not None:
            children.append(BasicNode(component="Text", text=title, metadata={"extensions": {"parrot_role": "title"}}))
        description = props.get("description")
        if description is not None:
            children.append(
                BasicNode(
                    component="Text",
                    text=description,
                    metadata={"extensions": {"parrot_role": "description"}},
                )
            )

        layer_items = [
            BasicNode(
                component="Text",
                text=_layer_summary_text(layer),
                metadata={"extensions": {"parrot_role": "layer"}},
            )
            for layer in (props.get("layers") or [])
        ]
        extensions: dict[str, Any] = {"parrot_role": "layer-summary"}
        if "data" in props:
            extensions["parrot_layer_data"] = props["data"]
        children.append(BasicNode(component="Column", children=layer_items, metadata={"extensions": extensions}))

        return BasicNode(
            id=component.id,
            component="Card",
            child=BasicNode(component="Column", children=children),
            metadata={"extensions": {"parrot_variant": "map"}},
        )
