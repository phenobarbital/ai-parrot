"""Golden + contract tests for Chart/DataTable/Map components (FEAT-470 TASK-2539, v1.0)."""

import json
from pathlib import Path

from parrot.outputs.a2ui.catalog import get_component, validate_envelope
from parrot.outputs.a2ui.catalog.base import to_components
from parrot.outputs.a2ui.catalog.parrot import chart, datatable
from parrot.outputs.a2ui.catalog.parrot import map as map_mod
from parrot.outputs.a2ui.models import ChildTemplate, Component, CreateSurface

GOLDEN_DIR = Path(__file__).parent / "golden"


def _dump(tree) -> bytes:
    """Deterministic serialization of a lowered tree."""
    return json.dumps(tree.model_dump(mode="json", exclude_none=True), sort_keys=True, indent=2).encode() + b"\n"


def _validates(tree) -> None:
    flat = to_components(tree)
    # Provide a stand-in for any ChildTemplate source id referenced by the
    # tree so validate_envelope's dangling-child check doesn't fire on the
    # (deliberately unresolved) bind-time reference.
    root = Component(id="root", component="Column", children=[c.id for c in flat])
    surface = CreateSurface(surfaceId="s", catalogId="https://parrot.dev/catalogs/v1", components=[root, *flat])
    validate_envelope(surface)


def _chart_component() -> Component:
    return Component(
        id="blk-000",
        component="Chart",
        title="Revenue by Region",
        type="bar",
        x="region",
        y=["q1", "q2"],
        showLegend=True,
        data={"path": "/charts/blk-000"},
    )


def _datatable_component() -> Component:
    return Component(
        id="blk-001",
        component="DataTable",
        title="Sales",
        columns=[
            {"name": "region", "title": "Region"},
            {"name": "total", "type": "number"},
        ],
        totalRows=42,
        truncated=True,
        data={"path": "/tables/blk-001"},
    )


def _map_component() -> Component:
    return Component(
        id="blk-002",
        component="Map",
        title="Stores",
        description="Store locations",
        # FEAT-473: MAP_SCHEMA is now derived from StructuredMapConfig/MapLayer —
        # layer items carry the full MapLayer vocabulary (`layer` id, not `name`/`type`).
        layers=[
            {
                "layer": "stores",
                "labelField": "name",
                "markerColor": "blue",
                "totalCount": 12,
                "capped": False,
            }
        ],
        viewport={"center": [40.0, -3.0], "zoom": 5},
        data={"path": "/maps/blk-002"},
    )


class TestChartComponent:
    def test_chart_registered_in_catalog(self):
        entry = get_component("Chart")
        assert entry.definition.requires_actions is False

    def test_chart_schema_accepts_structured_vocabulary(self):
        props = chart.CHART_SCHEMA["properties"]
        assert {"type", "x", "y", "showLegend"} <= set(props)

    def test_chart_schema_type_enum_includes_new_chart_types(self):
        """FEAT-527: gauge/funnel/waterfall/heatmap/treemap parity."""
        enum = chart.CHART_SCHEMA["properties"]["type"]["enum"]
        for t in ("gauge", "funnel", "waterfall", "heatmap", "treemap", "donut", "radar"):
            assert t in enum

    def test_chart_schema_has_layout(self):
        """FEAT-527: layout ('full'/'half') added to StructuredChartConfig."""
        props = chart.CHART_SCHEMA["properties"]
        assert "layout" in props
        # Optional[Literal[...]] renders as anyOf: [{enum: [...]}, {type: null}].
        layout_enum = next(
            branch["enum"] for branch in props["layout"]["anyOf"] if "enum" in branch
        )
        assert set(layout_enum) == {"full", "half"}

    def test_chart_lowering_golden(self):
        comp = _chart_component()
        one = _dump(chart.ChartComponent().lower(comp, {}))
        two = _dump(chart.ChartComponent().lower(comp, {}))
        assert one == two
        assert one == (GOLDEN_DIR / "chart_lowered.json").read_bytes()

    def test_chart_lowered_tree_has_no_echarts_config(self):
        tree = chart.ChartComponent().lower(_chart_component(), {})
        blob = json.dumps(tree.model_dump(mode="json"))
        # No ECharts option object should leak into a lowered Basic tree.
        assert '"option"' not in blob
        assert "echarts" not in blob.lower()

    def test_chart_emits_v1_primitives(self):
        # The chart's binding stays live (bake-time concern) — strip it before
        # validating structure against the basic catalog.
        comp = Component(id="blk-000", component="Chart", title="X", type="bar", x="a", y=["b"])
        tree = chart.ChartComponent().lower(comp, {})
        _validates(tree)


class TestDataTableComponent:
    def test_datatable_registered_in_catalog(self):
        assert get_component("DataTable").definition.requires_actions is False

    def test_datatable_lowering_golden(self):
        comp = _datatable_component()
        one = _dump(datatable.DataTableComponent().lower(comp, {}))
        two = _dump(datatable.DataTableComponent().lower(comp, {}))
        assert one == two
        assert one == (GOLDEN_DIR / "datatable_lowered.json").read_bytes()

    def test_datatable_lowers_to_child_template(self):
        tree = datatable.DataTableComponent().lower(_datatable_component(), {})
        body = tree.child.children[-1]
        assert isinstance(body.children, ChildTemplate)
        assert body.children.path == "/tables/blk-001"
        assert body.template_source is not None
        assert body.children.component_id == body.template_source.id

    def test_datatable_emits_v1_primitives(self):
        comp = Component(id="t1", component="DataTable", columns=[{"name": "a"}, {"name": "b"}])
        tree = datatable.DataTableComponent().lower(comp, {})
        flat = to_components(tree)
        root = Component(id="root", component="Column", children=[c.id for c in flat])
        surface = CreateSurface(surfaceId="s", catalogId="https://parrot.dev/catalogs/v1", components=[root, *flat])
        validate_envelope(surface)


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
        blob = json.dumps(tree.model_dump(mode="json"))
        assert "/maps/blk-002" in blob and '"path"' in blob

    def test_map_emits_v1_primitives(self):
        comp = Component(id="m1", component="Map", layers=[{"name": "l"}])
        _validates(map_mod.MapComponent().lower(comp, {}))
