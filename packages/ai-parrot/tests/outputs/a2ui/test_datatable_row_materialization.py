"""``DataTable`` row materialization via ``ChildTemplate`` (FEAT-470 TASK-2539, v1.0).

Pre-v1.0, ``lower()`` eagerly walked an already-RESOLVED row list into
``Row``/``Text`` nodes at lowering time (a two-phase contract coupled to
FEAT-273's bake pass). v1.0 replaces this entirely: ``lower()`` ALWAYS emits a
single row-pattern ``ChildTemplate`` (never eager per-row nodes) — the bake
pass (TASK-2538) is the ONLY place row lists are ever materialized, via
``@index``/relative-path template expansion (spec §2/§5). These tests pin
that end-to-end contract (lowering -> bake) for DataTable specifically.
"""

from __future__ import annotations

import pytest

pytest.importorskip("jsonpointer")

from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.catalog import (
    parrot as _all_parrot_components,  # noqa: F401
)
from parrot.outputs.a2ui.catalog.base import to_components
from parrot.outputs.a2ui.catalog.parrot import datatable
from parrot.outputs.a2ui.models import (
    ChildTemplate,
    Component,
    CreateSurface,
)

COLUMNS = [{"name": "region", "title": "Region"}, {"name": "total", "type": "number"}]


def _component(**props) -> Component:
    payload = {"id": "blk-001", "component": "DataTable", "title": "Sales", "columns": COLUMNS}
    payload.update(props)
    return Component(**payload)


def _lower(component: Component):
    return datatable.DataTableComponent().lower(component, {})


def _rows_body(tree):
    """The Column node carrying the ChildTemplate (last child of the wrapper Column)."""
    return tree.child.children[-1]


def _surface_and_bake(component: Component, data_model: dict) -> list[dict]:
    tree = _lower(component)
    flat = to_components(tree)
    root = Component(id="root", component="Column", children=[c.id for c in flat])
    surface = CreateSurface(
        surfaceId="s",
        catalogId="https://parrot.dev/catalogs/v1",
        components=[root, *flat],
        dataModel=data_model,
    )
    return bake_envelope(surface)


class TestLoweringAlwaysEmitsChildTemplate:
    def test_no_eager_rows_at_lowering_time(self):
        rows = _rows_body(_lower(_component(data={"path": "/tables/blk-001"})))
        assert isinstance(rows.children, ChildTemplate)
        assert rows.template_source is not None

    def test_default_table_path_when_data_not_bound(self):
        rows = _rows_body(_lower(_component()))
        assert rows.children.path == "/tables/blk-001"

    def test_explicit_data_binding_path_is_honored(self):
        rows = _rows_body(_lower(_component(data={"path": "/custom/rows"})))
        assert rows.children.path == "/custom/rows"


class TestBakedRowsMaterialize:
    def test_resolved_rows_become_row_and_text_nodes(self):
        baked = _surface_and_bake(
            _component(data={"path": "/tables/blk-001"}),
            {"tables": {"blk-001": [{"region": "North", "total": 10}, {"region": "South", "total": 20}]}},
        )
        row_clones = [c for c in baked if c["id"].startswith("blk-001-row-")]
        assert len(row_clones) == 2
        # Cells follow declared column order.
        assert row_clones[0]["children"] is not None  # Row of cell ids
        cell_ids_0 = row_clones[0]["children"]
        cells_0 = [next(c for c in baked if c["id"] == cid) for cid in cell_ids_0]
        assert [c["text"] for c in cells_0] == ["North", 10]

    def test_cells_use_declared_column_order_via_relative_path(self):
        baked = _surface_and_bake(
            _component(data={"path": "/tables/blk-001"}),
            {"tables": {"blk-001": [{"total": 10, "region": "North"}]}},
        )
        row = next(c for c in baked if c["id"] == "blk-001-row-0")
        cells = [next(c for c in baked if c["id"] == cid) for cid in row["children"]]
        assert [c["text"] for c in cells] == ["North", 10]

    def test_empty_row_list_produces_no_clones(self):
        baked = _surface_and_bake(_component(data={"path": "/tables/blk-001"}), {"tables": {"blk-001": []}})
        assert not [c for c in baked if c["id"].startswith("blk-001-row-")]

    def test_totalrows_and_truncated_survive_in_extensions(self):
        rows = _rows_body(_lower(_component(totalRows=42, truncated=True)))
        extensions = rows.metadata.extensions.root
        assert extensions["parrot_total_rows"] == 42
        assert extensions["parrot_truncated"] is True


class TestHeaderIsUnaffected:
    def test_header_still_uses_column_titles_then_names(self):
        tree = _lower(_component())
        header = tree.child.children[1]
        assert header.component == "Row"
        assert [cell.model_extra["text"] for cell in header.children] == ["Region", "total"]
