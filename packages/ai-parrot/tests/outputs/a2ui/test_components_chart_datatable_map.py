"""Golden + contract tests for Chart/DataTable/Map components (TASK-1724)."""

import json
from pathlib import Path

from parrot.outputs.a2ui.catalog import get_component
from parrot.outputs.a2ui.catalog.components import chart, datatable, map as map_mod
from parrot.outputs.a2ui.models import Component

GOLDEN_DIR = Path(__file__).parent / "golden"


def _dump(tree) -> bytes:
    """Deterministic serialization of a lowered tree."""
    return json.dumps(tree.model_dump(), sort_keys=True).encode()


def _chart_component() -> Component:
    return Component(
        id="blk-000",
        component="Chart",
        properties={
            "title": "Revenue by Region",
            "type": "bar",
            "x": "region",
            "y": ["q1", "q2"],
            "showLegend": True,
            "data": {"$bind": "/charts/blk-000"},
        },
    )


def _datatable_component() -> Component:
    return Component(
        id="blk-001",
        component="DataTable",
        properties={
            "title": "Sales",
            "columns": [
                {"name": "region", "title": "Region"},
                {"name": "total", "type": "number"},
            ],
            "totalRows": 42,
            "truncated": True,
            "data": {"$bind": "/tables/blk-001"},
        },
    )


def _map_component() -> Component:
    return Component(
        id="blk-002",
        component="Map",
        properties={
            "title": "Stores",
            "description": "Store locations",
            "layers": [{"name": "stores", "type": "markers"}],
            "viewport": {"center": [40.0, -3.0], "zoom": 5},
            "data": {"$bind": "/maps/blk-002"},
        },
    )


class TestChartComponent:
    def test_chart_registered_in_catalog(self):
        entry = get_component("Chart")
        assert entry.definition.requires_actions is False

    def test_chart_schema_accepts_structured_vocabulary(self):
        props = chart.CHART_SCHEMA["properties"]
        assert {"type", "x", "y", "showLegend"} <= set(props)

    def test_chart_lowering_golden(self):
        comp = _chart_component()
        one = _dump(chart.ChartComponent().lower(comp, {}))
        two = _dump(chart.ChartComponent().lower(comp, {}))
        assert one == two
        assert one == (GOLDEN_DIR / "chart_lowered.json").read_bytes()

    def test_chart_lowered_tree_has_no_echarts_config(self):
        tree = chart.ChartComponent().lower(_chart_component(), {})
        blob = json.dumps(tree.model_dump())
        # No ECharts option object should leak into a lowered Basic tree.
        assert '"option"' not in blob
        assert "echarts" not in blob.lower()


class TestDataTableComponent:
    def test_datatable_registered_in_catalog(self):
        assert get_component("DataTable").definition.requires_actions is False

    def test_datatable_lowering_golden(self):
        comp = _datatable_component()
        one = _dump(datatable.DataTableComponent().lower(comp, {}))
        two = _dump(datatable.DataTableComponent().lower(comp, {}))
        assert one == two
        assert one == (GOLDEN_DIR / "datatable_lowered.json").read_bytes()


class TestMapComponent:
    def test_map_registered_in_catalog(self):
        assert get_component("Map").definition.requires_actions is False

    def test_map_lowering_golden(self):
        comp = _map_component()
        one = _dump(map_mod.MapComponent().lower(comp, {}))
        two = _dump(map_mod.MapComponent().lower(comp, {}))
        assert one == two
        assert one == (GOLDEN_DIR / "map_lowered.json").read_bytes()

    def test_lowering_preserves_data_bindings(self):
        tree = map_mod.MapComponent().lower(_map_component(), {})
        blob = json.dumps(tree.model_dump())
        assert "/maps/blk-002" in blob and "$bind" in blob
