"""Tests for FEAT-473 TASK-2561 — core structured-output adapter + builders."""

from __future__ import annotations

import pytest
from parrot.models.outputs import (
    StructuredChartConfig,
    StructuredMapConfig,
    StructuredTableConfig,
)
from parrot.outputs.a2ui.adapters.structured import (
    DEFAULT_ROW_LIMIT,
    ROWS_PATH,
    chart_to_surface,
    config_to_component_props,
    map_to_surface,
    root_component,
    table_to_surface,
)
from parrot.outputs.a2ui.builders import build_map
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID
from parrot.outputs.a2ui.serialization import serialize


@pytest.fixture
def chart_cfg() -> StructuredChartConfig:
    return StructuredChartConfig(
        type="bar",
        x="label",
        y=["a", "b"],
        stacked=True,
        trendline=True,
        xAxisLabel="Label",
        yAxisLabel="Value",
        palette=["#111111", "#222222"],
        colorBySign=True,
    )


@pytest.fixture
def map_cfg_two_layers() -> StructuredMapConfig:
    return StructuredMapConfig(
        layers=[
            {
                "layer": "layer-a",
                "columns": [{"name": "x", "type": "string", "title": "X"}],
                "markerColor": "red",
                "tooltipTemplate": "{x}",
                "labelField": "x",
            },
            {
                "layer": "layer-b",
                "columns": [{"name": "y", "type": "string", "title": "Y"}],
                "markerColor": "blue",
            },
        ],
        viewport={"center": (1.0, 2.0), "zoom": 5},
        query={"point": (1.0, 2.0), "radius": 10.0, "unit": "km"},
    )


@pytest.fixture
def rows_1500() -> list[dict]:
    return [{"label": f"row-{i}", "a": i, "b": i * 2} for i in range(1500)]


def test_chart_to_surface_round_trip(chart_cfg):
    rows = [{"label": "x", "a": 1, "b": 2}]
    surface = chart_to_surface(chart_cfg, rows, surface_id="chart-1")
    expected_props = config_to_component_props(chart_cfg)
    expected_props["data"] = {"path": ROWS_PATH}
    root = surface.components[0]
    assert root.id == "root"
    assert root.component == "Chart"
    assert root.model_extra == expected_props
    assert surface.data_model["rows"] == rows


def test_table_to_surface_row_cap(rows_1500):
    cfg = StructuredTableConfig(columns=[{"name": "label", "type": "string", "title": "Label"}])
    surface = table_to_surface(cfg, rows_1500, surface_id="table-1", row_limit=1000)
    root = surface.components[0]
    assert len(surface.data_model["rows"]) == 1000
    assert root.model_extra["truncated"] is True
    assert root.model_extra["totalRows"] == 1500


def test_table_to_surface_empty_rows_still_builds():
    cfg = StructuredTableConfig(columns=[{"name": "a", "type": "string", "title": "A"}])
    surface = table_to_surface(cfg, [], surface_id="table-empty")
    root = surface.components[0]
    assert surface.data_model["rows"] == []
    assert root.model_extra["totalRows"] == 0
    assert root.model_extra["truncated"] is False


def test_map_to_surface_layers_paths(map_cfg_two_layers):
    layer_features = [[{"x": 1}, {"x": 2}], [{"y": "a"}]]
    surface = map_to_surface(map_cfg_two_layers, layer_features, surface_id="map-1")
    root = surface.components[0]
    layers = root.model_extra["layers"]
    assert layers[0]["data"] == {"path": "/layers/0/features"}
    assert layers[1]["data"] == {"path": "/layers/1/features"}
    assert layers[0]["totalCount"] == 2
    assert layers[1]["totalCount"] == 1
    assert surface.data_model["layers"][0]["features"] == [{"x": 1}, {"x": 2}]
    assert surface.data_model["layers"][1]["features"] == [{"y": "a"}]


def test_map_to_surface_empty_layer():
    cfg = StructuredMapConfig(layers=[{"layer": "l1", "columns": [{"name": "x", "type": "string", "title": "X"}]}])
    surface = map_to_surface(cfg, [[]], surface_id="map-empty")
    assert surface.data_model["layers"][0]["features"] == []
    assert surface.components[0].model_extra["layers"][0]["totalCount"] == 0
    assert surface.components[0].model_extra["layers"][0]["capped"] is False


def test_map_to_surface_row_cap_sets_capped(rows_1500):
    cfg = StructuredMapConfig(layers=[{"layer": "l1", "columns": [{"name": "label", "type": "string", "title": "L"}]}])
    surface = map_to_surface(cfg, [rows_1500], surface_id="map-cap", row_limit=DEFAULT_ROW_LIMIT)
    layer = surface.components[0].model_extra["layers"][0]
    assert layer["totalCount"] == 1500
    assert layer["capped"] is True
    assert len(surface.data_model["layers"][0]["features"]) == 1000


def test_build_map_validates_tool_origin():
    surface = build_map(layers=[{"layer": "l1", "columns": [{"name": "x", "type": "string", "title": "X"}]}])
    assert surface.components[0].component == "Map"


def test_surface_serializes_v1_envelope(chart_cfg):
    surface = chart_to_surface(chart_cfg, [{"label": "x", "a": 1, "b": 2}], surface_id="chart-1")
    env = serialize(surface)
    assert env["version"] == "v1.0"
    assert "createSurface" in env
    root = root_component(env)
    assert root["id"] == "root"
    assert env["createSurface"]["catalogId"] == DEFAULT_CATALOG_ID
