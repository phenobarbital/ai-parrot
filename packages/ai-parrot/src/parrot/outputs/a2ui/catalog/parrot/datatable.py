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


def _lower_row(row: Any, column_names: list[Any]) -> BasicNode:
    """Lower one resolved row to a ``Row`` of ``Text`` cells (pure, deterministic).

    Cells follow the DECLARED column order, so a table never renders its columns
    in dict-insertion order. Mapping rows are read by column name; sequence rows
    positionally; a scalar row degrades to a single cell.

    Args:
        row: One resolved row — a mapping keyed by column name, a sequence of
            cell values, or a scalar.
        column_names: Column ``name`` values in declared order.

    Returns:
        A ``Row`` node whose children are one ``Text`` cell per column.
    """
    if isinstance(row, dict):
        # No declared columns is degenerate (the schema requires them); fall back
        # to the row's own key order so data still reaches the surface.
        keys = column_names or list(row)
        values = [row.get(name) for name in keys]
    elif isinstance(row, (list, tuple)):
        count = len(column_names) or len(row)
        values = [row[i] if i < len(row) else None for i in range(count)]
    else:
        values = [row]

    return BasicNode(
        component="Row",
        properties={"role": "row"},
        children=[
            BasicNode(component="Text", properties={"role": "cell", "text": value})
            for value in values
        ],
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
        if "totalRows" in props:
            body_props["totalRows"] = props["totalRows"]
        if props.get("truncated"):
            body_props["truncated"] = True

        # Two-phase contract (spec §7):
        #  * REQUEST-live — ``data`` is still a binding expression: pass it through
        #    untouched for renderers that resolve it client-side.
        #  * CONFIGURE-bake — the bake pass already replaced the binding with the
        #    row list, so materialise one Row of Text cells per row. Without this
        #    the rows stay in an inert property and every static renderer emits an
        #    empty table (the SSR-HTML renderer only draws Text/Image leaves).
        data = props.get("data")
        row_nodes: list[BasicNode] = []
        if isinstance(data, list):
            column_names = [col.get("name") for col in (props.get("columns") or [])]
            row_nodes = [_lower_row(row, column_names) for row in data]
        elif "data" in props:
            body_props["data"] = data

        children.append(
            BasicNode(component="Column", properties=body_props, children=row_nodes)
        )

        return BasicNode(
            component="Card",
            properties={"variant": "table", "componentId": component.id},
            children=children,
        )
