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
