"""A2UI ``Map`` catalog component (Module 5, FEAT-470 TASK-2539 — v1.0 lowering).

Schema vocabulary is adapted from ``StructuredMapConfig``/``MapLayer``/``MapViewport``
(``parrot.models.outputs``): ``layers``, ``viewport``, ``baseLayer``, ``title``,
``description``. The INPUT-ONLY ``data`` array is replaced by a data-model binding.

``lower()`` degrades a Map to a static-friendly Basic tree (title/description Text
plus a layer-summary Column). Interactive tiles are the folium-map renderer's native
path (Module 7, satellite) — no geo/folium markup appears in the lowered tree.
"""

from __future__ import annotations

from typing import Any

from parrot.outputs.a2ui.catalog import register_component
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree
from parrot.outputs.a2ui.models import Component

MAP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "baseLayer": {"type": "string", "description": "Base tile layer id."},
        "viewport": {
            "type": "object",
            "properties": {
                "center": {"type": "array", "items": {"type": "number"}},
                "zoom": {"type": "number"},
            },
        },
        "layers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                },
                "required": ["name"],
            },
        },
        "data": {
            "description": "Data-model binding ({'path': '/pointer'}) to geo features.",
        },
    },
    "required": ["layers"],
}

MAP_INSTRUCTIONS = (
    "Use Map for geospatial data. Declare `layers` (each with `name`/`type`), an "
    "optional `viewport` (center/zoom) and `baseLayer`. Bind features with "
    "`data: {\"path\": \"/pointer\"}`. On static surfaces the map degrades to a "
    "titled layer summary. Display-only."
)


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
            children.append(
                BasicNode(
                    component="Text", text=title, metadata={"extensions": {"parrot_role": "title"}}
                )
            )
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
                text=layer.get("name", ""),
                metadata={"extensions": {"parrot_role": "layer"}},
            )
            for layer in (props.get("layers") or [])
        ]
        extensions: dict[str, Any] = {"parrot_role": "layer-summary"}
        if "data" in props:
            extensions["parrot_layer_data"] = props["data"]
        children.append(
            BasicNode(
                component="Column", children=layer_items, metadata={"extensions": extensions}
            )
        )

        return BasicNode(
            id=component.id,
            component="Card",
            child=BasicNode(component="Column", children=children),
            metadata={"extensions": {"parrot_variant": "map"}},
        )
