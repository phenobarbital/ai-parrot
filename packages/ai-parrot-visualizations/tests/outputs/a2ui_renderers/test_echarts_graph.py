"""Tests for native Graph support in the ECharts renderer (FEAT-529 Module 6, TASK-2888)."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("jsonpointer")

from parrot.outputs.a2ui.catalog.viz_core import VIZ_CORE_CATALOG_ID
from parrot.outputs.a2ui.models import Component, CreateSurface
from parrot.outputs.a2ui.renderers import get_a2ui_renderer
from parrot.outputs.a2ui_renderers.echarts import EChartsRenderer

pytestmark = pytest.mark.asyncio


def _graph_envelope() -> CreateSurface:
    return CreateSurface(
        surfaceId="main",
        catalogId="https://parrot.dev/catalogs/v1",
        components=[
            Component(
                id="root",
                component="Graph",
                catalogId=VIZ_CORE_CATALOG_ID,
                kind="flowchart",
                direction="TB",
                nodes=[{"id": "a", "label": "Start"}, {"id": "b", "label": "End"}],
                edges=[{"from": "a", "to": "b", "label": "go"}],
                accessibleDescription="A tiny graph.",
            )
        ],
    )


class TestEChartsCapabilitiesIncludeVizCore:
    def test_echarts_capabilities_include_viz_core(self):
        caps = EChartsRenderer.capabilities
        assert VIZ_CORE_CATALOG_ID in caps.supported_catalog_ids
        assert "Graph" in caps.supported_components
        assert "Chart" in caps.supported_components  # legacy unchanged

    def test_resolves_via_registry(self):
        assert get_a2ui_renderer("echarts") is EChartsRenderer


class TestEChartsGraphOption:
    async def test_echarts_graph_option(self):
        env = _graph_envelope()
        artifact = await EChartsRenderer().render(env)
        option = json.loads(artifact.content)

        series = option["series"][0]
        assert series["type"] == "graph"
        assert series["layout"] == "none"
        assert len(series["data"]) == 2
        assert len(series["links"]) == 1

        by_id = {entry["id"]: entry for entry in series["data"]}
        assert isinstance(by_id["a"]["x"], (int, float))
        assert isinstance(by_id["a"]["y"], (int, float))
        assert by_id["a"]["x"] != by_id["b"]["x"] or by_id["a"]["y"] != by_id["b"]["y"]

        link = series["links"][0]
        assert link["source"] == "a"
        assert link["target"] == "b"

    async def test_graph_option_deterministic(self):
        env = _graph_envelope()
        one = (await EChartsRenderer().render(env)).content
        two = (await EChartsRenderer().render(env)).content
        assert one == two

    async def test_graph_dispatch_is_catalog_aware(self):
        """A `Graph` component WITHOUT a viz-core catalogId does not intercept."""
        env = CreateSurface(
            surfaceId="main",
            catalogId="https://parrot.dev/catalogs/v1",
            components=[
                Component(
                    id="root",
                    component="Graph",  # no catalogId override -> resolves to Parrot default
                    nodes=[{"id": "a"}, {"id": "b"}],
                    edges=[{"from": "a", "to": "b"}],
                )
            ],
        )
        with pytest.raises(ValueError, match="requires a 'Chart' or viz-core 'Graph'"):
            await EChartsRenderer().render(env)

    async def test_graph_state_maps_to_category(self):
        env = CreateSurface(
            surfaceId="main",
            catalogId="https://parrot.dev/catalogs/v1",
            components=[
                Component(
                    id="root",
                    component="Graph",
                    catalogId=VIZ_CORE_CATALOG_ID,
                    nodes=[{"id": "a", "state": "failed"}, {"id": "b", "state": "completed"}],
                    edges=[{"from": "a", "to": "b"}],
                )
            ],
        )
        option = json.loads((await EChartsRenderer().render(env)).content)
        categories = option["series"][0]["categories"]
        by_id = {entry["id"]: entry for entry in option["series"][0]["data"]}
        assert categories[by_id["a"]["category"]]["name"] == "critical"
        assert categories[by_id["b"]["category"]]["name"] == "good"


class TestLegacyChartUnaffected:
    async def test_legacy_chart_still_dispatches(self):
        env = CreateSurface(
            surfaceId="main",
            catalogId="https://parrot.dev/catalogs/v1",
            components=[
                Component(id="root", component="Chart", type="bar", x="month", y=["rev"], title="Sales"),
            ],
        )
        option = json.loads((await EChartsRenderer().render(env)).content)
        assert "series" in option
        assert option["series"][0]["type"] == "bar"
