"""A2UI ``DataTable`` catalog component (Module 3).

Schema vocabulary is adapted from ``StructuredTableConfig``/``TableColumn``
(``parrot.models.outputs``): ``columns`` (name/type/title/format), ``totalRows``,
``truncated``. The INPUT-ONLY ``data`` array is replaced by a data-model binding.
The Pydantic class is not imported into the wire format.
"""

from __future__ import annotations

from typing import Any

from parrot.outputs.a2ui.catalog import register_component
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree
from parrot.outputs.a2ui.models import Component

DATATABLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "columns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                    "title": {"type": "string"},
                    "format": {"type": "string"},
                },
                "required": ["name"],
            },
        },
        "totalRows": {"type": "integer"},
        "truncated": {"type": "boolean", "default": False},
        "data": {
            "description": "Data-model binding ({'$bind': '/pointer'}) to the rows.",
        },
    },
    "required": ["columns"],
}

DATATABLE_INSTRUCTIONS = (
    "Use DataTable to present tabular rows. Declare `columns` (each with `name` and "
    "optional `type`/`title`/`format`). Bind rows with `data: {\"$bind\": \"/pointer\"}`. "
    "Set `totalRows`/`truncated` when the row set is capped. Display-only."
)


@register_component("DataTable")
class DataTableComponent:
    """The ``DataTable`` catalog component (display-only, ``requires_actions=False``)."""

    SCHEMA = DATATABLE_SCHEMA
    INSTRUCTIONS = DATATABLE_INSTRUCTIONS

    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:
        """Lower a DataTable to a Basic Catalog tree (pure, deterministic)."""
        props = component.properties
        children: list[BasicNode] = []

        title = props.get("title")
        if title is not None:
            children.append(
                BasicNode(component="Text", properties={"role": "title", "text": title})
            )

        header_cells = [
            BasicNode(
                component="Text",
                properties={
                    "role": "column-header",
                    "text": col.get("title") or col.get("name", ""),
                },
            )
            for col in (props.get("columns") or [])
        ]
        children.append(
            BasicNode(component="Row", properties={"role": "header"}, children=header_cells)
        )

        body_props: dict[str, Any] = {"role": "rows"}
        if "data" in props:
            body_props["data"] = props["data"]
        if "totalRows" in props:
            body_props["totalRows"] = props["totalRows"]
        if props.get("truncated"):
            body_props["truncated"] = True
        children.append(BasicNode(component="Column", properties=body_props))

        return BasicNode(
            component="Card",
            properties={"variant": "table", "componentId": component.id},
            children=children,
        )
