"""Unit tests for the ECharts renderer (TASK-1731)."""

import json

import pytest

pytest.importorskip("jsonpointer")

from parrot.outputs.a2ui.models import Component, CreateSurface
from parrot.outputs.a2ui.renderers import get_a2ui_renderer
from parrot.outputs.a2ui_renderers.echarts import EChartsRenderer

pytestmark = pytest.mark.asyncio


def _chart_envelope(title="Sales", data_binding=True) -> CreateSurface:
    props = {"type": "bar", "x": "month", "y": ["rev"], "title": title}
    if data_binding:
        props["data"] = {"path": "/rows"}
    return CreateSurface(
        surfaceId="main",
        catalogId="https://parrot.dev/catalogs/v1",
        components=[Component(id="root", component="Chart", **props)],
        dataModel={"rows": [{"month": "Jan", "rev": 10}, {"month": "Feb", "rev": 20}]},
    )


class TestEChartsRenderer:
    async def test_capabilities_declared(self):
        caps = EChartsRenderer.capabilities
        assert caps.interactive is False
        assert caps.supports_actions is False
        assert caps.output == "application/json"

    async def test_resolves_via_registry(self):
        assert get_a2ui_renderer("echarts") is EChartsRenderer

    async def test_option_payload_deterministic(self):
        env = _chart_envelope()
        one = (await EChartsRenderer().render(env)).content
        two = (await EChartsRenderer().render(env)).content
        assert one == two
        option = json.loads(one)
        assert option["xAxis"]["data"] == ["Jan", "Feb"]
        assert option["series"][0]["data"] == [10, 20]

    async def test_html_wrap_inlines_vendored_bundle_no_cdn(self):
        env = _chart_envelope()
        art = await EChartsRenderer().render(env, wrap_html=True)
        doc = art.content.decode()
        assert art.mime_type == "text/html"
        assert "cdn.jsdelivr.net" not in doc
        assert "<script src=" not in doc  # bundle is inlined, not linked
        assert "echarts.init" in doc

    async def test_wrap_escapes_data_values(self):
        env = _chart_envelope(title="<script>alert(1)</script>")
        doc = (await EChartsRenderer().render(env, wrap_html=True)).content.decode()
        # Title in <title> is HTML-escaped; option JSON neutralizes '<'.
        assert "<script>alert(1)</script>" not in doc
        assert "\\u003c" in doc or "&lt;script&gt;" in doc

    async def test_output_has_zero_live_bindings(self):
        doc = (await EChartsRenderer().render(_chart_envelope())).content.decode()
        assert '"path"' not in doc

    async def test_no_chart_raises(self):
        env = CreateSurface(
            surfaceId="m",
            catalogId="https://parrot.dev/catalogs/v1",
            components=[Component(id="root", component="InfoCard", title="x")],
        )
        with pytest.raises(ValueError):
            await EChartsRenderer().render(env)


class TestTASK2544:
    """FEAT-470 TASK-2544: echarts declares supported_components + reads top-level props."""

    async def test_echarts_capabilities(self):
        caps = EChartsRenderer.capabilities
        assert caps.supported_components == {"Chart"}

    async def test_echarts_reads_top_level_props(self):
        """Chart props (v1.0) live top-level, not nested under "properties"."""
        env = _chart_envelope()
        option = json.loads((await EChartsRenderer().render(env)).content)
        assert option["title"]["text"] == "Sales"
        assert option["series"][0]["name"] == "rev"


class TestSiblingDegradationRecorded:
    """Post-review fix: non-Chart siblings must not be silently dropped."""

    def _multi_component_envelope(self) -> CreateSurface:
        return CreateSurface(
            surfaceId="main",
            catalogId="https://parrot.dev/catalogs/v1",
            components=[
                Component(
                    id="chart-1",
                    component="Chart",
                    type="bar",
                    x="month",
                    y=["rev"],
                    title="Sales",
                    data=[{"month": "Jan", "rev": 10}],
                ),
                Component(id="note-1", component="Text", text="a sibling note"),
            ],
        )

    async def test_sibling_recorded_in_degraded_metadata(self):
        art = await EChartsRenderer().render(self._multi_component_envelope())
        degraded = art.metadata.get("degraded", [])
        assert any(d["id"] == "note-1" and d["component"] == "Text" for d in degraded)

    async def test_html_wrap_also_records_sibling_degradation(self):
        art = await EChartsRenderer().render(self._multi_component_envelope(), wrap_html=True)
        degraded = art.metadata.get("degraded", [])
        assert any(d["id"] == "note-1" for d in degraded)

    async def test_single_chart_no_degradations(self):
        art = await EChartsRenderer().render(_chart_envelope())
        assert art.metadata.get("degraded", []) == []


class TestNewChartTypes:
    """FEAT-527: gauge/funnel/waterfall/heatmap/treemap/donut/radar native ECharts options."""

    @pytest.mark.parametrize(
        "ctype,series_type",
        [
            ("gauge", "gauge"),
            ("funnel", "funnel"),
            ("treemap", "treemap"),
            ("heatmap", "heatmap"),
            ("donut", "pie"),
            ("radar", "radar"),
        ],
    )
    async def test_new_chart_types_series(self, ctype, series_type):
        props = {"type": ctype, "x": "m", "y": ["v"], "data": [{"m": "a", "v": 1}, {"m": "b", "v": 2}]}
        option = EChartsRenderer()._build_option(props)
        assert option["series"][0]["type"] == series_type

    async def test_waterfall_uses_stacked_placeholder(self):
        option = EChartsRenderer()._build_option(
            {"type": "waterfall", "x": "m", "y": ["v"], "data": [{"m": "a", "v": 5}, {"m": "b", "v": -2}]}
        )
        assert len(option["series"]) == 2
        assert all(s.get("stack") for s in option["series"])

    async def test_gauge_ignores_x_single_value_per_series(self):
        option = EChartsRenderer()._build_option(
            {"type": "gauge", "x": "m", "y": ["v1", "v2"], "data": [{"m": "a", "v1": 1, "v2": 2}]}
        )
        assert len(option["series"]) == 2
        assert option["series"][0]["data"] == [{"value": 1, "name": "v1"}]
        assert option["series"][1]["data"] == [{"value": 2, "name": "v2"}]

    async def test_funnel_data_from_first_y_only(self):
        option = EChartsRenderer()._build_option(
            {
                "type": "funnel",
                "x": "m",
                "y": ["v1", "v2"],
                "data": [{"m": "a", "v1": 10, "v2": 99}, {"m": "b", "v1": 5, "v2": 1}],
            }
        )
        assert option["series"][0]["data"] == [
            {"value": 10, "name": "a"},
            {"value": 5, "name": "b"},
        ]

    async def test_treemap_data_shape(self):
        option = EChartsRenderer()._build_option(
            {"type": "treemap", "x": "m", "y": ["v"], "data": [{"m": "a", "v": 10}]}
        )
        assert option["series"][0]["data"] == [{"name": "a", "value": 10}]

    async def test_heatmap_data_and_visual_map(self):
        option = EChartsRenderer()._build_option(
            {
                "type": "heatmap",
                "x": "m",
                "y": ["v1", "v2"],
                "data": [{"m": "a", "v1": 1, "v2": 2}, {"m": "b", "v1": 3, "v2": 4}],
            }
        )
        assert option["series"][0]["data"] == [
            [0, 0, 1],
            [0, 1, 2],
            [1, 0, 3],
            [1, 1, 4],
        ]
        assert "visualMap" in option
        assert option["xAxis"]["data"] == ["a", "b"]
        assert option["yAxis"]["data"] == ["v1", "v2"]

    async def test_radar_indicator_from_categories(self):
        option = EChartsRenderer()._build_option(
            {"type": "radar", "x": "m", "y": ["v"], "data": [{"m": "a", "v": 1}, {"m": "b", "v": 2}]}
        )
        # Code-review regression guard: indicators used to carry no "max",
        # which produces degenerate/flat radar axes for real data — each
        # indicator's max is now the largest value across y-columns at that
        # row (row "a" -> v=1, row "b" -> v=2).
        assert option["radar"]["indicator"] == [{"name": "a", "max": 1}, {"name": "b", "max": 2}]
        assert option["series"][0]["data"][0]["value"] == [1, 2]

    async def test_radar_indicator_omits_max_when_no_numeric_value(self):
        option = EChartsRenderer()._build_option(
            {"type": "radar", "x": "m", "y": ["v"], "data": [{"m": "a", "v": None}]}
        )
        assert option["radar"]["indicator"] == [{"name": "a"}]

    async def test_donut_radius_applied(self):
        option = EChartsRenderer()._build_option({"type": "donut", "x": "m", "y": ["v"], "data": [{"m": "a", "v": 1}]})
        assert option["series"][0]["radius"] == ["40%", "70%"]

    async def test_row_native_types_forward_palette(self):
        # Code-review regression guard: palette/colorBySign used to only be
        # applied in the standard per-y-column path — the row-native early
        # return silently dropped them for gauge/funnel/treemap/heatmap/
        # waterfall/radar, even though the adapter forwards them correctly.
        for chart_type in ("gauge", "funnel", "treemap", "heatmap", "waterfall", "radar"):
            option = EChartsRenderer()._build_option(
                {
                    "type": chart_type,
                    "x": "m",
                    "y": ["v"],
                    "data": [{"m": "a", "v": 1}, {"m": "b", "v": -2}],
                    "palette": ["#111111", "#222222"],
                }
            )
            assert option["color"] == ["#111111", "#222222"], chart_type

    async def test_waterfall_color_by_sign_targets_the_delta_series(self):
        option = EChartsRenderer()._build_option(
            {
                "type": "waterfall",
                "x": "m",
                "y": ["v"],
                "data": [{"m": "a", "v": 10}, {"m": "b", "v": -5}],
                "colorBySign": True,
                "positiveColor": "#0a0",
                "negativeColor": "#a00",
            }
        )
        assert option["visualMap"]["seriesIndex"] == 1
        assert option["visualMap"]["pieces"] == [
            {"max": 0, "color": "#a00"},
            {"min": 0, "color": "#0a0"},
        ]

    async def test_gauge_color_by_sign_is_not_applied(self):
        # gauge has no flat signed scalar series for a piecewise visualMap
        # to target — colorBySign is a documented bar/waterfall-only feature.
        option = EChartsRenderer()._build_option(
            {"type": "gauge", "x": "m", "y": ["v"], "data": [{"m": "a", "v": 1}], "colorBySign": True}
        )
        assert "visualMap" not in option
