"""A2UI ``DataTable`` catalog component (Module 5, FEAT-470 TASK-2539 — v1.0 lowering).

Schema vocabulary is adapted from ``StructuredTableConfig``/``TableColumn``
(``parrot.models.outputs``): ``columns`` (name/type/title/format), ``totalRows``,
``truncated``. The INPUT-ONLY ``data`` array is replaced by a data-model binding.

v1.0 rows are a ``ChildTemplate`` (spec §2/§5): a single row-pattern
:class:`~parrot.outputs.a2ui.catalog.base.BasicNode` (one ``Text`` cell per
declared column, bound via a column-name-RELATIVE ``{"path": "<name>"}``)
materialized once per data-model row by the bake pass (TASK-2538), instead of
this module eagerly walking an already-resolved row list.
"""

from __future__ import annotations

from typing import Any

from parrot.outputs.a2ui.catalog import register_component
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree
from parrot.outputs.a2ui.models import ChildTemplate, Component

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
            "description": "Data-model binding ({'path': '/pointer'}) to the rows.",
        },
    },
    "required": ["columns"],
}

DATATABLE_INSTRUCTIONS = (
    "Use DataTable to present tabular rows. Declare `columns` (each with `name` and "
    'optional `type`/`title`/`format`). Bind rows with `data: {"path": "/pointer"}`. '
    "Set `totalRows`/`truncated` when the row set is capped. Display-only."
)


@register_component("DataTable")
class DataTableComponent:
    """The ``DataTable`` catalog component (display-only, ``requires_actions=False``)."""

    SCHEMA = DATATABLE_SCHEMA
    INSTRUCTIONS = DATATABLE_INSTRUCTIONS

    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:
        """Lower a DataTable to a Basic Catalog ``Card`` tree with a row template."""
        props = component.model_extra or {}
        columns = props.get("columns") or []

        header_cells = [
            BasicNode(
                component="Text",
                text=col.get("title") or col.get("name", ""),
                metadata={"extensions": {"parrot_role": "column-header"}},
            )
            for col in columns
        ]

        top_children: list[BasicNode] = []
        title = props.get("title")
        if title is not None:
            top_children.append(
                BasicNode(component="Text", text=title, metadata={"extensions": {"parrot_role": "title"}})
            )
        top_children.append(
            BasicNode(
                component="Row",
                children=header_cells,
                metadata={"extensions": {"parrot_role": "header"}},
            )
        )

        data = props.get("data")
        table_path = data["path"] if isinstance(data, dict) and "path" in data else f"/tables/{component.id}"
        row_id = f"{component.id}-row"
        row_template = BasicNode(
            id=row_id,
            component="Row",
            children=[
                BasicNode(
                    component="Text",
                    text={"path": col["name"]},
                    metadata={"extensions": {"parrot_role": "cell"}},
                )
                for col in columns
                if col.get("name")
            ],
            metadata={"extensions": {"parrot_role": "row"}},
        )

        body_extensions: dict[str, Any] = {"parrot_role": "rows"}
        if "totalRows" in props:
            body_extensions["parrot_total_rows"] = props["totalRows"]
        if props.get("truncated"):
            body_extensions["parrot_truncated"] = True

        top_children.append(
            BasicNode(
                component="Column",
                children=ChildTemplate(componentId=row_id, path=table_path),
                template_source=row_template,
                metadata={"extensions": body_extensions},
            )
        )

        return BasicNode(
            id=component.id,
            component="Card",
            child=BasicNode(component="Column", children=top_children),
            metadata={"extensions": {"parrot_variant": "table", "parrot_component_id": component.id}},
        )
