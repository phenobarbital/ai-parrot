"""Unit tests for the interactive-HTML renderer (FEAT-324, Module 7;
rewritten to v1.0 by FEAT-470 TASK-2544)."""

import html
import json
import re

import pytest

pytest.importorskip("jsonpointer")

from parrot.outputs.a2ui.models import Component, CreateSurface
from parrot.outputs.a2ui.renderers import get_a2ui_renderer
from parrot.outputs.a2ui_renderers.interactive_html import (
    InteractiveHTMLRenderer,
)

pytestmark = pytest.mark.asyncio


def _envelope(*components: Component, data_model=None) -> CreateSurface:
    return CreateSurface(
        surfaceId="main",
        catalogId="https://parrot.dev/catalogs/v1",
        components=list(components),
        dataModel=data_model or {},
    )


class TestInteractiveHTMLRenderer:
    async def test_capabilities_declared(self):
        caps = InteractiveHTMLRenderer.capabilities
        assert caps.interactive is True
        assert caps.supports_actions is False
        assert caps.supports_updates is False
        assert caps.output == "text/html"

    async def test_registration_resolves(self):
        assert get_a2ui_renderer("interactive-html") is InteractiveHTMLRenderer

    async def test_interactive_html_self_contained(self):
        env = _envelope(
            Component(
                id="root",
                component="Chart",
                type="bar",
                x="day",
                y=["actual", "budget"],
                data={"path": "/rows"},
                title="Actual vs Budget",
            ),
            data_model={"rows": [{"day": "Mon", "actual": 10, "budget": 8}]},
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        assert doc.startswith("<!DOCTYPE html>")
        assert art.mime_type == "text/html"
        assert art.surface == "interactive-html"
        # Zero external network references — works from file://. A vendored
        # library's license-header comment MAY mention its homepage URL as
        # plain text; only actual resource-loading references are forbidden
        # (matches the SSR-HTML self-containment test's approach).
        externals = re.findall(r'(?:src|href)="https?://[^"]+"', doc)
        assert externals == []
        assert "@import" not in doc
        assert "<script src=" not in doc
        assert "<link " not in doc

    async def test_datamodel_embedded_and_parseable(self):
        data_model = {"rows": [{"day": "Mon", "actual": 10, "budget": 8}]}
        env = _envelope(
            Component(id="root", component="InfoCard", title="T"),
            data_model=data_model,
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        match = re.search(r'<script type="application/json" id="report-data">(.*?)</script>', doc, re.DOTALL)
        assert match is not None
        parsed = json.loads(match.group(1))
        assert parsed == data_model

    async def test_chart_rendered_from_properties(self):
        env = _envelope(
            Component(
                id="root",
                component="Chart",
                type="bar",
                x="day",
                y=["actual", "budget"],
                data={"path": "/rows"},
                title="Actual vs Budget",
            ),
            data_model={"rows": [{"day": "Mon", "actual": 10, "budget": 8}]},
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        assert "Actual vs Budget" in doc
        assert "data-chart-config=" in doc
        assert "<canvas" in doc
        # Vendored Chart.js bundle is inlined (license header preserved).
        assert "Chart.js" in doc
        assert "MIT License" in doc
        # Multi-y-column chart gets metric-toggle buttons.
        assert "data-metric-toggle-for=" in doc
        assert "data-metric-index=" in doc

    async def test_chart_with_tabs_renders_day_tabs(self):
        env = _envelope(
            Component(
                id="root",
                component="Chart",
                type="line",
                x="division",
                y=["variance"],
                tabs={"path": "/tabs"},
                title="Daily Variance",
            ),
            data_model={
                "tabs": [
                    {"label": "Jul 1", "data": [{"division": "Sales", "variance": 10}]},
                    {"label": "Jul 22", "data": [{"division": "Sales", "variance": -5}]},
                ]
            },
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        assert 'data-tabs-for="' in doc
        assert 'data-tab-index="0"' in doc
        assert 'data-tab-index="1"' in doc
        assert "Jul 1" in doc and "Jul 22" in doc

    async def test_datatable_rendered_with_sort_hooks(self):
        env = _envelope(
            Component(
                id="root",
                component="DataTable",
                title="Ledger",
                columns=[{"name": "division", "title": "Division"}, {"name": "rev"}],
                data={"path": "/rows"},
            ),
            data_model={"rows": [{"division": "Sales", "rev": 100}, {"division": "Ops", "rev": 50}]},
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        assert "data-sort-table" in doc
        assert 'data-sort-key="division"' in doc
        assert 'data-sort-key="rev"' in doc
        assert "Sales" in doc and "Ops" in doc
        assert "<table" in doc

    async def test_non_chart_components_render_server_side(self):
        env = _envelope(
            Component(id="k0", component="KPICard", label="Revenue", value=100),
            Component(id="c1", component="InfoCard", title="Notes"),
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        assert "Revenue" in doc
        assert "Notes" in doc

    async def test_infographic_nested_chart_and_datatable(self):
        env = _envelope(
            Component(
                id="root",
                component="Infographic",
                title="Budget Variance",
                sections=[
                    {
                        "heading": "Overview",
                        "components": [
                            {
                                "component": "Chart",
                                "properties": {
                                    "type": "bar",
                                    "x": "day",
                                    "y": ["actual"],
                                    "data": {"path": "/rows"},
                                },
                            },
                            {
                                "component": "DataTable",
                                "properties": {
                                    "columns": [{"name": "day"}],
                                    "data": {"path": "/rows"},
                                },
                            },
                        ],
                    }
                ],
            ),
            data_model={"rows": [{"day": "Mon", "actual": 10}]},
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        assert "Budget Variance" in doc
        assert "Overview" in doc
        assert "data-chart-config=" in doc
        assert "data-sort-table" in doc

    async def test_sort_and_tab_hooks_present_in_behavior_js(self):
        env = _envelope(Component(id="root", component="InfoCard", title="T"))
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        assert "data-sort-table" in doc  # behavior JS references the hook name
        assert "data-tabs-for" in doc
        assert "data-metric-toggle-for" in doc


class TestTASK2544:
    """FEAT-470 TASK-2544: 18-primitive dispatch, Tabs/List/Divider/inputs."""

    async def test_interactive_html_renders_new_primitives(self):
        """Tabs/List/Divider/inputs are present in the DOM (spec acceptance
        criterion)."""
        env = _envelope(
            Component(
                id="root",
                component="Column",
                children=["tabs1", "list1", "div1", "tf1", "cb1"],
            ),
            Component(
                id="tabs1",
                component="Tabs",
                tabs=[{"title": "Tab A", "child": "ta1"}, {"title": "Tab B", "child": "tb1"}],
            ),
            Component(id="ta1", component="Text", text="content A"),
            Component(id="tb1", component="Text", text="content B"),
            Component(id="list1", component="List", direction="horizontal", children=["lt1"]),
            Component(id="lt1", component="Text", text="list item"),
            Component(id="div1", component="Divider", axis="horizontal"),
            Component(id="tf1", component="TextField", label="Name", value="Alice"),
            Component(id="cb1", component="CheckBox", label="Agree", value=True),
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        assert "data-tabs=" in doc
        assert "data-tabs-panes=" in doc
        assert "content A" in doc and "content B" in doc
        assert "list item" in doc
        assert '<hr class="a2ui-divider-h">' in doc
        assert "Name" in doc and "Alice" in doc
        assert "Agree" in doc
        assert art.metadata.get("degraded", []) == []

    async def test_interactive_chart_reads_top_level_props(self):
        """Chart props (v1.0) live top-level, not nested under "properties"."""
        env = _envelope(
            Component(
                id="root",
                component="Chart",
                type="bar",
                x="day",
                y=["actual"],
                data=[{"day": "Mon", "actual": 5}],
                title="Top Level",
            )
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()
        assert "Top Level" in doc
        assert '"day":"Mon"' in doc.replace(" ", "") or "Mon" in doc

    async def test_unsupported_component_degrades(self):
        env = _envelope(Component(id="root", component="NotARealComponent", foo="bar"))
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()
        assert "no renderer" in doc.lower() or "not supported" in doc.lower()
        assert len(art.metadata["degraded"]) == 1


class TestNewChartTypesDegradation:
    """FEAT-527: donut/radar are Chart.js natives; gauge/funnel/waterfall/
    heatmap/treemap have no Chart.js equivalent and must degrade — visibly
    AND recorded, never silently."""

    @pytest.mark.parametrize(
        "chart_type", ["gauge", "funnel", "waterfall", "heatmap", "treemap"]
    )
    async def test_unsupported_chart_type_degrades_to_bar_with_record(self, chart_type):
        env = _envelope(
            Component(
                id="root", component="Chart", type=chart_type, x="m", y=["v"],
                data=[{"m": "a", "v": 1}],
            )
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        assert any(chart_type in d.get("reason", "") for d in art.metadata["degraded"])
        # Visible caption naming the original type.
        assert chart_type in doc
        assert "rendered as bar" in doc
        # The embedded Chart.js config itself must degrade to "bar".
        config = json.loads(re.search(r'data-chart-config="([^"]*)"', doc).group(1).replace("&quot;", '"'))
        assert config["type"] == "bar"
        # Self-contained invariant unaffected by the degradation caption.
        assert "<script src=" not in doc

    @pytest.mark.parametrize("chart_type,expected", [("donut", "doughnut"), ("radar", "radar")])
    async def test_donut_and_radar_are_chartjs_natives_not_degraded(self, chart_type, expected):
        env = _envelope(
            Component(
                id="root", component="Chart", type=chart_type, x="m", y=["v"],
                data=[{"m": "a", "v": 1}],
            )
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        assert art.metadata.get("degraded", []) == []
        assert "rendered as bar" not in doc
        config = json.loads(re.search(r'data-chart-config="([^"]*)"', doc).group(1).replace("&quot;", '"'))
        assert config["type"] == chart_type

    async def test_supported_chart_type_no_degradation(self):
        env = _envelope(
            Component(id="root", component="Chart", type="bar", x="m", y=["v"], data=[{"m": "a", "v": 1}])
        )
        art = await InteractiveHTMLRenderer().render(env)
        assert art.metadata.get("degraded", []) == []

    async def test_nested_chart_in_infographic_records_degradation(self):
        """Degradations from a Chart nested inside an Infographic section
        must reach the top-level RenderedArtifact.metadata['degraded']."""
        env = _envelope(
            Component(
                id="root",
                component="Infographic",
                title="T",
                sections=[
                    {
                        "heading": "S",
                        "components": [
                            {
                                "component": "Chart",
                                "properties": {
                                    "type": "gauge", "x": "m", "y": ["v"],
                                    "data": [{"m": "a", "v": 1}],
                                },
                            }
                        ],
                    }
                ],
            )
        )
        art = await InteractiveHTMLRenderer().render(env)
        assert any("gauge" in d.get("reason", "") for d in art.metadata["degraded"])


class TestMapDispatch:
    """FEAT-522 TASK-2793: Map dispatch integration — top-level, Infographic-
    nested, and the offline srcdoc escaping-loophole guardrail."""

    async def test_map_top_level_renders_iframe(self):
        env = _envelope(
            Component(
                id="map1",
                component="Map",
                title="Stores",
                layers=[{"layer": "stores", "data": [{"lat": 1.0, "lon": 2.0}]}],
                viewport={"center": [1.0, 2.0], "zoom": 6},
            )
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()
        assert '<iframe sandbox="allow-scripts allow-popups"' in doc
        assert "stores | label=" not in doc  # old text-degradation marker absent

    async def test_map_nested_in_infographic_renders_iframe(self):
        """Mirrors flex_dashboard.py's Proximity Staffing section shape: a Map
        nested inside an Infographic section's `components` descriptor list —
        the exact `_render_descriptor` code path (not `_render_top`)."""
        env = _envelope(
            Component(
                id="info1",
                component="Infographic",
                title="Proximity Staffing",
                sections=[
                    {
                        "heading": "Store Coverage",
                        "components": [
                            {
                                "component": "Map",
                                "properties": {
                                    "layers": [{"layer": "stores", "data": [{"lat": 1.0, "lon": 2.0}]}],
                                    "viewport": {"center": [1.0, 2.0], "zoom": 6},
                                },
                            }
                        ],
                    }
                ],
            )
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()
        assert '<iframe sandbox="allow-scripts allow-popups"' in doc
        assert "stores | label=" not in doc

    async def test_map_iframe_srcdoc_has_zero_external_resources(self):
        """Closes the escaping loophole in test_document_shell.py's existing
        `test_self_contained_invariant` guardrail: that test only inspects the
        OUTER, still-HTML-escaped document — `<script src=` never appears
        literally there even with a CDN leak inside the iframe, since
        HTML-escaping turns `<` into `&lt;`. This test decodes the `srcdoc`
        attribute value first, THEN asserts."""
        env = _envelope(
            Component(
                id="map1",
                component="Map",
                layers=[{"layer": "stores", "data": [{"lat": 1.0, "lon": 2.0}]}],
            )
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()

        m = re.search(r'srcdoc="([^"]*)"', doc)
        assert m, "expected an iframe srcdoc attribute"
        decoded = html.unescape(m.group(1))

        assert '<script src="http' not in decoded
        assert 'href="http' not in decoded
        assert 'src="http' not in decoded
        # Positive control: the decoded content really is a full folium
        # document (not an empty/truncated match) and DOES use offline
        # data: URIs for its own resources.
        assert "data:text/javascript;base64," in decoded
        assert "data:text/css;base64," in decoded

    def test_interactive_html_importable_without_folium(self, monkeypatch):
        """Post-review regression guard: `folium_map.py` builds its
        `_OFFLINE_URL_MAP` eagerly at ITS OWN import time (requires
        `folium`). A top-level `from .folium_map import build_map_document`
        in THIS module would make `folium` a hard, unconditional
        import-time dependency of the whole `interactive-html` surface —
        breaking Chart/DataTable/Infographic-only users without the
        optional `map` extra. `build_map_document` must be imported
        lazily, inside `_render_map()` only."""
        import builtins
        import importlib
        import sys

        real_import = builtins.__import__

        def _blocked_import(name, *args, **kwargs):
            if name == "folium" or name.startswith("folium."):
                raise ImportError("folium blocked for this test")
            return real_import(name, *args, **kwargs)

        for mod_name in ("parrot.outputs.a2ui_renderers.interactive_html", "parrot.outputs.a2ui_renderers.folium_map"):
            sys.modules.pop(mod_name, None)

        monkeypatch.setattr(builtins, "__import__", _blocked_import)
        try:
            reimported = importlib.import_module("parrot.outputs.a2ui_renderers.interactive_html")
            assert reimported.InteractiveHTMLRenderer is not None
        finally:
            monkeypatch.undo()
            sys.modules.pop("parrot.outputs.a2ui_renderers.interactive_html", None)
            sys.modules.pop("parrot.outputs.a2ui_renderers.folium_map", None)
            importlib.import_module("parrot.outputs.a2ui_renderers.interactive_html")
