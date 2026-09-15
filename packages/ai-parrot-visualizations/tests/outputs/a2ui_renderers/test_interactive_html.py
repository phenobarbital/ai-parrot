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

    @pytest.mark.parametrize("chart_type", ["gauge", "funnel", "waterfall", "heatmap", "treemap"])
    async def test_unsupported_chart_type_degrades_to_bar_with_record(self, chart_type):
        env = _envelope(
            Component(
                id="root",
                component="Chart",
                type=chart_type,
                x="m",
                y=["v"],
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
                id="root",
                component="Chart",
                type=chart_type,
                x="m",
                y=["v"],
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
        env = _envelope(Component(id="root", component="Chart", type="bar", x="m", y=["v"], data=[{"m": "a", "v": 1}]))
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
                                    "type": "gauge",
                                    "x": "m",
                                    "y": ["v"],
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


class TestHtmlDocumentSandboxedIframe:
    """FEAT-527: HtmlDocument embeds in a sandboxed iframe — never lowered,
    never evaluated by the host page."""

    async def test_htmldocument_embedded_in_sandboxed_iframe(self):
        env = _envelope(
            Component(
                id="root",
                component="HtmlDocument",
                title="Doc",
                html="<html><body><script>alert(1)</script></body></html>",
            )
        )
        art = await InteractiveHTMLRenderer().render(env)
        out = art.content.decode()

        assert 'sandbox="allow-scripts"' in out
        assert "srcdoc=" in out
        assert "allow-same-origin" not in out
        assert "<script>alert(1)</script>" not in out  # only the escaped form inside srcdoc
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out
        assert "<script src=" not in out
        assert "Doc" in out

    async def test_htmldocument_src_url_variant(self):
        env = _envelope(
            Component(id="root", component="HtmlDocument", title="Doc", srcUrl="https://x/infographic-a.html")
        )
        art = await InteractiveHTMLRenderer().render(env)
        out = art.content.decode()

        assert 'sandbox="allow-scripts"' in out
        assert 'src="https://x/infographic-a.html"' in out
        assert "srcdoc=" not in out

    async def test_htmldocument_no_degradation_recorded(self):
        env = _envelope(Component(id="root", component="HtmlDocument", title="Doc", html="<p>hi</p>"))
        art = await InteractiveHTMLRenderer().render(env)
        assert art.metadata.get("degraded", []) == []

    async def test_htmldocument_nested_in_infographic(self):
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
                                "component": "HtmlDocument",
                                "properties": {"title": "Nested Doc", "html": "<p>hi</p>"},
                            }
                        ],
                    }
                ],
            )
        )
        art = await InteractiveHTMLRenderer().render(env)
        out = art.content.decode()
        assert 'sandbox="allow-scripts"' in out
        assert "Nested Doc" in out


class TestChartKeyIsReadableAndSingular:
    """The chart key used to be a schema printed twice.

    "Events by week" showed a row of buttons reading `scheduled | in_progress
    | completed | missed | unfulfilled | cancelled` and, directly under it,
    Chart.js' own legend with the same six words — one of them a column key
    with an underscore in it.
    """

    pytestmark = pytest.mark.asyncio

    @staticmethod
    def _weekly_chart() -> CreateSurface:
        return CreateSurface(
            surfaceId="s",
            catalogId="c",
            components=[
                Component(
                    id="root",
                    component="Chart",
                    type="bar",
                    x="week",
                    y=["scheduled", "in_progress", "completed"],
                    title="Events by week",
                    data=[{"week": "2026-W36", "scheduled": 8, "in_progress": 1, "completed": 27}],
                )
            ],
            dataModel={},
        )

    async def test_a_series_is_named_not_keyed(self):
        doc = (await InteractiveHTMLRenderer().render(self._weekly_chart())).content.decode()
        assert ">In progress</button>" in doc
        # The raw key must not survive as the button's visible text. It still
        # appears inside the embedded config (it is how a row is looked up),
        # so this checks the RENDERED label, not the whole document.
        assert ">in_progress</button>" not in doc

    async def test_the_datasets_carry_the_same_names(self):
        # The toggles and the plot must not disagree about what a series is
        # called, so the readable names travel in the config beside `y`.
        doc = (await InteractiveHTMLRenderer().render(self._weekly_chart())).content.decode()
        assert "yLabels" in doc
        assert "In progress" in doc

    async def test_only_one_key_is_drawn(self):
        # The toggles carry the colours and the names, so Chart.js' built-in
        # legend would be a second key saying the same words.
        doc = (await InteractiveHTMLRenderer().render(self._weekly_chart())).content.decode()
        assert "&quot;showLegend&quot;: false" in doc or '"showLegend": false' in doc

    async def test_a_single_series_keeps_the_built_in_legend(self):
        # No toggles render for one y column, so nothing would name the series
        # if the legend were off too.
        envelope = CreateSurface(
            surfaceId="s",
            catalogId="c",
            components=[
                Component(
                    id="root",
                    component="Chart",
                    type="line",
                    x="week",
                    y=["completed"],
                    data=[{"week": "2026-W36", "completed": 27}],
                )
            ],
            dataModel={},
        )
        doc = (await InteractiveHTMLRenderer().render(envelope)).content.decode()
        # ...and it sits at the bottom too, so the key is in the same place
        # whether a chart has one series or six.
        assert 'position: "bottom"' in doc
        # The MARKUP, not the string: the runtime's own JS contains the
        # selector `[data-metric-toggle-for="...]` and the stylesheet contains
        # `.a2ui-metric-toggle`, both inlined into every document, so a bare
        # substring is true with no toggles rendered at all.
        assert '<div class="a2ui-metric-toggle"' not in doc
        assert "&quot;showLegend&quot;: true" in doc or '"showLegend": true' in doc

    async def test_the_key_sits_below_the_chart(self):
        doc = (await InteractiveHTMLRenderer().render(self._weekly_chart())).content.decode()
        assert doc.index("<canvas") < doc.index('<div class="a2ui-metric-toggle"')

    async def test_a_toggle_says_out_loud_whether_it_is_on(self):
        # The class paints the state; only aria-pressed reports it. Without
        # it the control is a button whose entire purpose — "this series is
        # currently hidden" — is visible and nothing else.
        doc = (await InteractiveHTMLRenderer().render(self._weekly_chart())).content.decode()
        assert 'aria-pressed="true"' in doc

    async def test_the_key_is_styled_at_all(self):
        # `.metricbtn` and `.daytab` carried no CSS whatsoever: browser
        # default buttons, and `.active` painted nothing, so a series
        # switched off looked exactly like one switched on.
        doc = (await InteractiveHTMLRenderer().render(self._weekly_chart())).content.decode()
        assert ".metricbtn," in doc or ".metricbtn {" in doc
        assert ".metricbtn:not(.active)" in doc
        assert ".metricbtn:focus-visible" in doc or ".metricbtn:focus-visible," in doc


class TestInteractiveChartTrendline:
    """The trendline the app draws and this surface used to drop.

    `StructuredChartConfig.trendline` reached the static ECharts renderer and
    the Svelte canvas, but the interactive surface ignored it — the same
    report showed a fitted line in the app and none in the exported HTML.
    """

    def _doc_and_config(self, doc: str) -> dict:
        raw = re.search(r'data-chart-config="([^"]*)"', doc).group(1)
        return json.loads(html.unescape(raw))

    async def test_a_requested_trendline_reaches_the_embedded_config(self):
        env = _envelope(
            Component(
                id="root",
                component="Chart",
                type="line",
                x="day",
                y=["actual"],
                data={"path": "/rows"},
                trendline=True,
            ),
            data_model={"rows": [{"day": "Mon", "actual": 10}, {"day": "Tue", "actual": 14}]},
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()
        assert self._doc_and_config(doc)["trendline"] is True

    async def test_a_chart_that_asked_for_nothing_carries_nothing(self):
        env = _envelope(
            Component(
                id="root", component="Chart", type="line", x="day", y=["actual"],
                data={"path": "/rows"},
            ),
            data_model={"rows": [{"day": "Mon", "actual": 10}]},
        )
        art = await InteractiveHTMLRenderer().render(env)
        assert "trendline" not in self._doc_and_config(art.content.decode())

    @pytest.mark.parametrize("chart_type", ["pie", "donut", "radar"])
    async def test_a_line_through_a_pie_is_never_drawn(self, chart_type):
        # The fit runs over row ORDER, and these have no axis for that to
        # mean anything along. Decided here, in Python, so the browser
        # runtime does not carry a second copy of the rule.
        env = _envelope(
            Component(
                id="root", component="Chart", type=chart_type, x="day", y=["actual"],
                data={"path": "/rows"}, trendline=True,
            ),
            data_model={"rows": [{"day": "Mon", "actual": 10}, {"day": "Tue", "actual": 14}]},
        )
        art = await InteractiveHTMLRenderer().render(env)
        assert "trendline" not in self._doc_and_config(art.content.decode())

    async def test_a_degraded_chart_is_a_bar_and_a_bar_can_carry_a_trend(self):
        # `waterfall` has no Chart.js equivalent and arrives as a bar. The
        # type tested is the final one, so the trend survives the degradation.
        env = _envelope(
            Component(
                id="root", component="Chart", type="waterfall", x="day", y=["actual"],
                data={"path": "/rows"}, trendline=True,
            ),
            data_model={"rows": [{"day": "Mon", "actual": 10}, {"day": "Tue", "actual": 14}]},
        )
        art = await InteractiveHTMLRenderer().render(env)
        config = self._doc_and_config(art.content.decode())
        assert config["type"] == "bar"
        assert config["trendline"] is True

    async def test_the_fit_is_computed_in_the_browser_not_baked_in(self):
        # The point of fitting client-side: `buildDatasets` runs again on
        # every day-tab switch and every FilterBar change, so the line must be
        # recomputed from the rows on screen. A server-baked array of points
        # would keep the slope of data the reader stopped looking at.
        env = _envelope(
            Component(
                id="root", component="Chart", type="bar", x="day", y=["actual"],
                data={"path": "/rows"}, trendline=True,
            ),
            data_model={"rows": [{"day": "Mon", "actual": 10}, {"day": "Tue", "actual": 14}]},
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()
        assert "function trendData(" in doc
        # The config carries the FLAG and the rows, never fitted points.
        config = self._doc_and_config(doc)
        assert set(config["data"][0]) == {"day", "actual"}

    async def test_the_fitted_line_never_borrows_a_meaningful_colour(self):
        # Colour is a judgement in these reports -- green is good news, red is
        # bad. Left to Chart.js the trend came out red, reading as an alarm
        # nobody raised. Grey, and the same grey the other two renderers use.
        env = _envelope(
            Component(
                id="root", component="Chart", type="line", x="day", y=["actual"],
                data={"path": "/rows"}, trendline=True,
            ),
            data_model={"rows": [{"day": "Mon", "actual": 10}, {"day": "Tue", "actual": 14}]},
        )
        art = await InteractiveHTMLRenderer().render(env)
        doc = art.content.decode()
        assert 'var TREND_COLOR = "#94a3b8"' in doc
        assert "borderColor: TREND_COLOR" in doc


class TestInteractiveKpiGrid:
    """Eight KPIs came out as eight full-width blocks.

    The stylesheet has always carried `.kpi-grid`, but the class was only
    attached to a Row of kpi Cards — and an Infographic section is a COLUMN
    whose first child is its heading, so the rule never fired.
    """

    def _section(self, *components) -> Component:
        return Component(
            id="root",
            component="Infographic",
            title="Report",
            sections=[{"heading": "Hero", "components": list(components)}],
        )

    def _kpi(self, label: str) -> dict:
        return {"component": "KPICard", "properties": {"label": label, "value": 1}}

    async def test_consecutive_kpi_cards_become_one_grid(self):
        env = _envelope(self._section(self._kpi("Events"), self._kpi("Completed"), self._kpi("Missed")))
        doc = (await InteractiveHTMLRenderer().render(env)).content.decode()
        assert doc.count('<div class="kpi-grid">') == 1
        grid = doc.split('<div class="kpi-grid">')[1]
        assert grid.count('class="a2ui-card kpi-card"') == 3

    async def test_a_chart_between_them_starts_a_second_grid(self):
        # Grouped by RUN, not by container: the same rule the Svelte canvas
        # uses. Two KPIs, a chart, then one more KPI is two grids, not one.
        chart = {
            "component": "Chart",
            "properties": {"type": "bar", "x": "day", "y": ["n"], "data": []},
        }
        env = _envelope(self._section(self._kpi("A"), self._kpi("B"), chart, self._kpi("C")))
        doc = (await InteractiveHTMLRenderer().render(env)).content.decode()
        assert doc.count('<div class="kpi-grid">') == 2
        assert "<canvas" in doc

    async def test_a_section_with_no_kpis_grows_no_grid(self):
        chart = {
            "component": "Chart",
            "properties": {"type": "bar", "x": "day", "y": ["n"], "data": []},
        }
        env = _envelope(self._section(chart))
        doc = (await InteractiveHTMLRenderer().render(env)).content.decode()
        assert '<div class="kpi-grid">' not in doc


class TestExportedDeltaReadsLikeTheApp:
    async def _card_doc(self, **props) -> str:
        env = _envelope(
            Component(id="root", component="KPICard", label="Metric", value=10, **props)
        )
        return (await InteractiveHTMLRenderer().render(env)).content.decode()

    async def test_the_direction_travels_and_is_now_drawn(self):
        # `data-trend` always travelled and the stylesheet's own comment
        # described an arrow — but nothing drew one, so the export reported
        # direction by the sign alone while the app showed a glyph.
        doc = await self._card_doc(delta="-55.4%", trend="down")
        assert 'data-trend="down"' in doc
        assert '.kpi-delta[data-trend="down"]::before' in doc

    async def test_an_unjudged_delta_is_ordinary_text_not_muted(self):
        # Same decision the Svelte card took: unjudged is not unimportant,
        # and muted weighed exactly as much as the period beside it.
        doc = await self._card_doc(delta="-55.4%", trend="down", higherIsBetter=None)
        assert 'data-sentiment="neutral"' in doc
        assert '.kpi-delta[data-sentiment="neutral"] { color: var(--neutral-text); }' in doc
        assert '.kpi-delta[data-sentiment="neutral"] { color: var(--neutral-muted); }' not in doc


class TestPrintingAnExportedReport:
    """Ctrl+P on an exported report, which is how it becomes a PDF.

    `layout-print.css` is a whole LAYOUT the PDF renderer selects
    server-side; an interactive document ships as `[data-layout="analytics"]`
    and never sees it. Until `print-media.css` the composed sheet carried no
    `@media print` rule at all.
    """

    async def _doc(self) -> str:
        env = _envelope(
            Component(
                id="root", component="Chart", type="bar", x="day", y=["a", "b"],
                data={"path": "/rows"},
            ),
            data_model={"rows": [{"day": "Mon", "a": 1, "b": 2}]},
        )
        return (await InteractiveHTMLRenderer().render(env)).content.decode()

    async def test_the_document_carries_print_rules(self):
        doc = await self._doc()
        assert "@media print" in doc

    async def test_colour_is_asked_for_explicitly(self):
        # Browsers drop background colours when printing unless the reader
        # ticked "Background graphics". Everything meaningful in this report
        # is a colour — the delta greens and reds, the table header band.
        assert "print-color-adjust: exact" in await self._doc()

    async def test_controls_that_do_nothing_on_paper_are_hidden(self):
        doc = await self._doc()
        # From the RULE, not from the prose: the stylesheet's own comment
        # mentions `@media print` before the block opens.
        block = doc[re.search(r"@media print\s*\{", doc).end():]
        for selector in (".a2ui-metric-toggle", ".a2ui-table-pager", ".filter-bar"):
            assert f"{selector},\n" in block or f"{selector} " in block

    async def test_the_pdf_layout_does_not_get_a_second_page_rule(self):
        # `layout-print.css` already owns the paged rules for WeasyPrint.
        # Two sources deciding one margin is worse than one.
        from parrot.outputs.formats.assets.design_system import DesignSystem

        assert "@media print" not in DesignSystem.stylesheet(layout="print")
        assert "@media print" in DesignSystem.stylesheet(layout="analytics")


class TestTableHeadersReadLikeAReport:
    """A report handed to a client had `store_id | store_name | rate` across
    the top of its tables: the database schema, read by someone who does not
    have it.
    """

    async def _headers(self, columns) -> str:
        env = _envelope(
            Component(
                id="root", component="DataTable", columns=columns,
                data={"path": "/rows"},
            ),
            data_model={"rows": [{"store_id": "BBY1", "scheduled": 2}]},
        )
        doc = (await InteractiveHTMLRenderer().render(env)).content.decode()
        return re.search(r"<thead><tr>(.*?)</tr></thead>", doc).group(1)

    async def test_a_declared_title_is_used_verbatim(self):
        head = await self._headers([{"name": "store_id", "title": "Store", "type": "string"}])
        assert ">Store</th>" in head
        assert "store_id</th>" not in head

    async def test_a_column_with_no_title_is_humanised_not_printed_raw(self):
        # The fallback of last resort, not the default: a recipe should name
        # its columns. But a key is never shown to a reader as-is.
        head = await self._headers([{"name": "open_clocks", "type": "integer"}])
        assert ">Open clocks</th>" in head

    async def test_a_numeric_header_aligns_with_its_figures(self):
        # Left-aligned over right-aligned numbers, a header labels the white
        # space beside its column rather than the column.
        head = await self._headers(
            [
                {"name": "store_id", "title": "Store", "type": "string"},
                {"name": "scheduled", "title": "Scheduled", "type": "integer"},
            ]
        )
        assert 'class="num">Scheduled</th>' in head
        assert 'class="num">Store</th>' not in head

    async def test_the_sticky_header_stays_opaque(self):
        # `position: sticky` plus a transparent background prints the header
        # and the first row on top of each other while the reader scrolls.
        env = _envelope(
            Component(
                id="root", component="DataTable",
                columns=[{"name": "a", "title": "A", "type": "string"}],
                data={"path": "/rows"},
            ),
            data_model={"rows": [{"a": "1"}]},
        )
        doc = (await InteractiveHTMLRenderer().render(env)).content.decode()
        assert "background: var(--panel-bg)" in doc


class TestPageBreaksDoNotWasteSheets:
    """Only what fits on a page may refuse to be split.

    Asking a block taller than the page to stay whole does not shrink it:
    the browser pushes the whole thing to the next sheet and leaves the
    current one blank. A seven-page report printed a half-empty first page
    and a third page holding nothing but a heading.
    """

    async def _print_block(self) -> str:
        env = _envelope(
            Component(id="root", component="Text", text="x"),
        )
        doc = (await InteractiveHTMLRenderer().render(env)).content.decode()
        return doc[re.search(r"@media print\s*\{", doc).end():]

    async def test_a_section_and_a_table_may_break_across_pages(self):
        block = await self._print_block()
        allowed = block[block.index('.a2ui-card[data-variant="infographic"]'):][:220]
        assert ".a2ui-section" in allowed
        assert ".a2ui-table-wrap" in allowed
        assert "break-inside: auto" in allowed

    async def test_a_card_and_a_chart_still_stay_whole(self):
        block = await self._print_block()
        kept = block[block.index(".kpi-card,"):][:200]
        assert ".a2ui-chart-wrap" in kept
        assert "break-inside: avoid" in kept

    async def test_a_heading_is_never_the_last_line_of_a_page(self):
        assert "break-after: avoid" in await self._print_block()


class TestChartsPrintSolid:
    """Chart.js fills with alpha when nothing says otherwise. That survives a
    screen and washes out on paper — printed, the bars read as ghosts.
    """

    async def _doc(self, **props) -> str:
        env = _envelope(
            Component(
                id="root", component="Chart", type="bar", x="day", y=["a", "b"],
                data={"path": "/rows"}, **props,
            ),
            data_model={"rows": [{"day": "Mon", "a": 1, "b": 2}]},
        )
        return (await InteractiveHTMLRenderer().render(env)).content.decode()

    async def test_series_colours_are_chosen_not_defaulted(self):
        doc = await self._doc()
        assert "var SERIES_COLORS" in doc
        assert "backgroundColor: color," in doc

    async def test_the_palette_holds_no_red_and_no_green(self):
        # Those two belong to the deltas, where they mean good news and bad.
        # In a chart colour is identity, and borrowing the verdict pair would
        # make "Missed" look like a judgement the chart is not making.
        doc = await self._doc()
        palette = re.search(r"var SERIES_COLORS = \[(.*?)\]", doc, re.S).group(1)
        for verdict in ("#dc2626", "#ef4444", "#10b981", "#059669", "#16a34a"):
            assert verdict not in palette

    async def test_an_author_palette_wins(self):
        doc = await self._doc(palette=["#111111", "#222222"])
        config = json.loads(html.unescape(re.search(r'data-chart-config="([^"]*)"', doc).group(1)))
        assert config["palette"] == ["#111111", "#222222"]

    async def test_a_chart_with_no_palette_carries_none(self):
        config = json.loads(
            html.unescape(re.search(r'data-chart-config="([^"]*)"', await self._doc()).group(1))
        )
        assert "palette" not in config

    async def test_chart_type_is_sized_for_paper(self):
        # The canvas is rasterised at screen size and scaled down to the page
        # width, taking its type with it: axis labels landed around seven
        # points.
        assert "Chart.defaults.font.size = 14" in await self._doc()


class TestChartsAreRedrawnForPaper:
    """A chart is drawn at screen width and rasterised; the printer scales
    that bitmap down to the page and takes the type with it.
    """

    async def _doc(self) -> str:
        env = _envelope(
            Component(
                id="root", component="Chart", type="bar", x="day", y=["a"],
                data={"path": "/rows"},
            ),
            data_model={"rows": [{"day": "Mon", "a": 1}]},
        )
        return (await InteractiveHTMLRenderer().render(env)).content.decode()

    async def test_the_runtime_reshapes_before_printing(self):
        doc = await self._doc()
        assert 'window.addEventListener("beforeprint", chartsForPrint)' in doc
        # And puts the screen back afterwards, so printing does not leave the
        # page looking like a print preview.
        assert 'window.addEventListener("afterprint", chartsForScreen)' in doc

    async def test_paper_gets_its_own_proportion(self):
        # A page is a fixed budget: the strip that suits a wide screen prints
        # as something too flat to read a bar in.
        doc = await self._doc()
        assert "var SCREEN_ASPECT = 3.2" in doc
        assert "var PRINT_ASPECT = 2.2" in doc

    async def test_a_missing_chart_does_not_break_the_print(self):
        # `resize()` on a destroyed chart throws; a print is not the moment
        # to discover that.
        doc = await self._doc()
        block = doc[doc.index("function resizeCharts(aspect)"):][:400]
        assert "try {" in block and "catch" in block


class TestPrintUndoesScreenOnlyPositioning:
    async def test_the_table_header_is_not_sticky_on_paper(self):
        # Sticky belongs to a scrolling viewport. Left on in print it cost the
        # header its text — the accent rule printed and the column names did
        # not — while `table-header-group` was already repeating it correctly.
        env = _envelope(
            Component(
                id="root", component="DataTable",
                columns=[{"name": "a", "title": "A", "type": "string"}],
                data={"path": "/rows"},
            ),
            data_model={"rows": [{"a": "1"}]},
        )
        doc = (await InteractiveHTMLRenderer().render(env)).content.decode()
        block = doc[re.search(r"@media print\s*\{", doc).end():]
        assert "position: static !important" in block

    async def test_print_does_not_force_a_canvas_height(self):
        # The runtime already sized the canvas for the page; forcing a height
        # on top of it letterboxed the drawing inside its own box.
        env = _envelope(
            Component(
                id="root", component="Chart", type="bar", x="d", y=["a"],
                data={"path": "/rows"},
            ),
            data_model={"rows": [{"d": "Mon", "a": 1}]},
        )
        doc = (await InteractiveHTMLRenderer().render(env)).content.decode()
        block = doc[re.search(r"@media print\s*\{", doc).end():]
        canvas_rule = block[block.index("\n    canvas {"):][:200]
        # Width leads and height follows. Constraining the height while the
        # canvas keeps its bitmap's proportion is what shrank the WIDTH to
        # about three quarters of the panel and left a white band beside
        # every chart — measured in print emulation, the canvas filled its
        # wrapper exactly, so the box was never the problem.
        assert "width: 100% !important" in canvas_rule
        assert "height: auto !important" in canvas_rule
        assert "max-height: none !important" in canvas_rule


class TestInteractiveCombination:
    """Chart.js has always drawn mixed datasets — it is how the trend line
    rides on a bar chart. All this needed was somewhere to say it.
    """

    async def _config(self, **props) -> dict:
        env = _envelope(
            Component(
                id="root", component="Chart", type="bar", x="week", y=["events", "rate"],
                data={"path": "/rows"}, **props,
            ),
            data_model={"rows": [{"week": "W1", "events": 27, "rate": 0.62}]},
        )
        doc = (await InteractiveHTMLRenderer().render(env)).content.decode()
        return json.loads(html.unescape(re.search(r'data-chart-config="([^"]*)"', doc).group(1)))

    async def test_the_marks_reach_the_embedded_config(self):
        config = await self._config(seriesTypes=[None, "line"])
        assert config["seriesTypes"] == [None, "line"]

    async def test_the_axes_reach_it_too(self):
        config = await self._config(seriesTypes=[None, "line"], seriesAxes=[None, "right"])
        assert config["seriesAxes"] == [None, "right"]

    async def test_a_chart_that_combines_nothing_carries_nothing(self):
        config = await self._config()
        assert "seriesTypes" not in config
        assert "seriesAxes" not in config

    async def test_the_second_scale_is_conditional_in_the_runtime(self):
        env = _envelope(
            Component(
                id="root", component="Chart", type="bar", x="week", y=["a"],
                data={"path": "/rows"},
            ),
            data_model={"rows": [{"week": "W1", "a": 1}]},
        )
        doc = (await InteractiveHTMLRenderer().render(env)).content.decode()
        # Built only when a series asked: naming an axis on every dataset
        # would put an empty ruler on the right of every chart.
        assert 'indexOf("right") === -1 ? undefined' in doc
