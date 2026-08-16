"""``DataTable`` row materialisation in the lowering (FEAT-273 Module 3/6).

The bake pass replaces a row binding with the resolved row list, but the
lowering used to leave that list in an inert ``data`` property on a childless
``Column``. Static renderers only draw ``Text``/``Image`` leaves, so every
baked table rendered empty. These tests pin both halves of the two-phase
contract: a live binding is passed through untouched, resolved rows become
``Row``/``Text`` nodes.
"""

import json

import pytest

from parrot.outputs.a2ui.catalog import components as _all_components  # noqa: F401
from parrot.outputs.a2ui.catalog.components import datatable
from parrot.outputs.a2ui.models import Component

COLUMNS = [{"name": "region", "title": "Region"}, {"name": "total", "type": "number"}]


def _component(**props) -> Component:
    payload = {"title": "Sales", "columns": COLUMNS}
    payload.update(props)
    return Component(id="blk-001", component="DataTable", properties=payload)


def _lower(component: Component):
    return datatable.DataTableComponent().lower(component, {})


def _rows_node(tree):
    (node,) = [
        child
        for child in tree.children
        if child.component == "Column" and child.properties.get("role") == "rows"
    ]
    return node


def _cells(row_node) -> list:
    return [child.properties.get("text") for child in row_node.children]


class TestLiveBindingPassthrough:
    def test_binding_is_preserved_and_no_rows_are_invented(self):
        tree = _lower(_component(data={"$bind": "/tables/blk-001"}))
        rows = _rows_node(tree)
        assert rows.properties["data"] == {"$bind": "/tables/blk-001"}
        assert rows.children == []

    def test_absent_data_yields_no_data_property(self):
        rows = _rows_node(_lower(_component()))
        assert "data" not in rows.properties
        assert rows.children == []


class TestBakedRowsMaterialise:
    def test_resolved_rows_become_row_and_text_nodes(self):
        tree = _lower(
            _component(data=[{"region": "North", "total": 10}, {"region": "South", "total": 20}])
        )
        rows = _rows_node(tree)
        assert [child.component for child in rows.children] == ["Row", "Row"]
        assert _cells(rows.children[0]) == ["North", 10]
        assert _cells(rows.children[1]) == ["South", 20]
        assert all(
            cell.properties["role"] == "cell"
            for row in rows.children
            for cell in row.children
        )

    def test_materialised_rows_drop_the_inert_data_property(self):
        # Keeping it would duplicate the whole row set inside the tree.
        rows = _rows_node(_lower(_component(data=[{"region": "North", "total": 1}])))
        assert "data" not in rows.properties

    def test_cells_follow_declared_column_order_not_dict_order(self):
        rows = _rows_node(_lower(_component(data=[{"total": 10, "region": "North"}])))
        assert _cells(rows.children[0]) == ["North", 10]

    def test_missing_keys_become_empty_cells(self):
        rows = _rows_node(_lower(_component(data=[{"region": "North"}])))
        assert _cells(rows.children[0]) == ["North", None]

    def test_extra_keys_outside_the_declared_columns_are_ignored(self):
        rows = _rows_node(
            _lower(_component(data=[{"region": "N", "total": 1, "secret": "x"}]))
        )
        assert _cells(rows.children[0]) == ["N", 1]

    def test_sequence_rows_map_positionally(self):
        rows = _rows_node(_lower(_component(data=[["North", 10], ["South"]])))
        assert _cells(rows.children[0]) == ["North", 10]
        assert _cells(rows.children[1]) == ["South", None]

    def test_scalar_row_degrades_to_a_single_cell(self):
        rows = _rows_node(_lower(_component(data=["North"])))
        assert _cells(rows.children[0]) == ["North"]

    def test_empty_row_list_renders_no_rows(self):
        rows = _rows_node(_lower(_component(data=[])))
        assert rows.children == []
        assert "data" not in rows.properties

    def test_rows_without_declared_columns_fall_back_to_row_keys(self):
        component = Component(
            id="blk-001",
            component="DataTable",
            properties={"columns": [], "data": [{"a": 1, "b": 2}]},
        )
        rows = _rows_node(_lower(component))
        assert _cells(rows.children[0]) == [1, 2]

    def test_totalrows_and_truncated_survive_materialisation(self):
        rows = _rows_node(
            _lower(_component(data=[{"region": "N", "total": 1}], totalRows=42, truncated=True))
        )
        assert rows.properties["totalRows"] == 42
        assert rows.properties["truncated"] is True

    @pytest.mark.parametrize(
        "data",
        [
            [{"region": "North", "total": 10}],
            {"$bind": "/tables/blk-001"},
        ],
    )
    def test_lowering_stays_pure(self, data):
        component = _component(data=data)
        one = json.dumps(_lower(component).model_dump(), sort_keys=True)
        two = json.dumps(_lower(component).model_dump(), sort_keys=True)
        assert one == two


class TestHeaderIsUnaffected:
    def test_header_still_uses_column_titles_then_names(self):
        tree = _lower(_component(data=[{"region": "N", "total": 1}]))
        (header,) = [
            child
            for child in tree.children
            if child.component == "Row" and child.properties.get("role") == "header"
        ]
        assert [cell.properties["text"] for cell in header.children] == ["Region", "total"]
