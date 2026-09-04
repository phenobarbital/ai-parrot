"""Unit tests for the SSR-HTML renderer (TASK-1729, rewritten to v1.0 by FEAT-470 TASK-2543)."""

import re

import pytest

pytest.importorskip("jsonpointer")

from parrot.outputs.a2ui.models import Component, CreateSurface  # noqa: E402
from parrot.outputs.a2ui.renderers import get_a2ui_renderer  # noqa: E402
from parrot.outputs.a2ui_renderers.ssr_html import SSRHTMLRenderer  # noqa: E402

pytestmark = pytest.mark.asyncio

_ALL_18_PRIMITIVES_ENVELOPE = CreateSurface(
    surfaceId="main",
    catalogId="https://parrot.dev/catalogs/v1",
    components=[
        Component(
            id="root",
            component="Column",
            children=[
                "t1",
                "img1",
                "icon1",
                "vid1",
                "aud1",
                "row1",
                "list1",
                "card1",
                "tabs1",
                "modal1",
                "div1",
                "btn1",
                "tf1",
                "cb1",
                "cp1",
                "sl1",
                "dt1",
            ],
        ),
        Component(id="t1", component="Text", text="hello"),
        Component(id="img1", component="Image", url="https://x/y.png", description="desc"),
        Component(id="icon1", component="Icon", name="home"),
        Component(id="vid1", component="Video", url="https://x/v.mp4", posterUrl="https://x/p.png"),
        Component(id="aud1", component="AudioPlayer", url="https://x/a.mp3", description="song"),
        Component(id="row1", component="Row", children=["rt1"]),
        Component(id="rt1", component="Text", text="row child"),
        Component(id="list1", component="List", direction="horizontal", children=["lt1"]),
        Component(id="lt1", component="Text", text="list child"),
        Component(id="card1", component="Card", child="ct1"),
        Component(id="ct1", component="Text", text="card child"),
        Component(id="tabs1", component="Tabs", tabs=[{"title": "Tab A", "child": "ta1"}]),
        Component(id="ta1", component="Text", text="tab content"),
        Component(id="modal1", component="Modal", trigger="btn1", content="mc1"),
        Component(id="mc1", component="Text", text="modal content"),
        Component(id="div1", component="Divider", axis="horizontal"),
        Component(id="btn1", component="Button", child="bt1", action={"event": {"name": "go"}}),
        Component(id="bt1", component="Text", text="Click me"),
        Component(id="tf1", component="TextField", label="Name", value="Alice"),
        Component(id="cb1", component="CheckBox", label="Agree", value=True),
        Component(
            id="cp1",
            component="ChoicePicker",
            label="Pick",
            options=[{"label": "A", "value": "a"}],
            value=["a"],
        ),
        Component(id="sl1", component="Slider", label="Vol", value=5, max=10),
        Component(id="dt1", component="DateTimeInput", label="When", value="2020-01-01"),
    ],
    dataModel={},
)


class TestSSRHTMLRenderer:
    async def test_capabilities_declared(self):
        caps = SSRHTMLRenderer.capabilities
        assert caps.interactive is False
        assert caps.supports_actions is False
        assert caps.output == "text/html"

    async def test_resolves_via_registry(self):
        assert get_a2ui_renderer("ssr_html") is SSRHTMLRenderer


class TestTASK2543:
    """FEAT-470 TASK-2543: renderer capabilities/degradation/18-primitive dispatch."""

    async def test_renderer_capabilities_declared(self):
        caps = SSRHTMLRenderer.capabilities
        assert "Text" in caps.supported_components
        assert "Video" in caps.supported_components
        assert len(caps.supported_components) == 18
        assert "https://parrot.dev/catalogs/v1" in caps.supported_catalog_ids

    async def test_ssr_html_all_primitives(self):
        """SSR renders an envelope with all 18 primitives without exception,
        with everything HTML-escaped and no external src/href leaking out."""
        art = await SSRHTMLRenderer().render(_ALL_18_PRIMITIVES_ENVELOPE)
        doc = art.content.decode()
        assert doc.startswith("<!DOCTYPE html>")
        assert art.mime_type == "text/html"
        assert art.metadata.get("degraded", []) == []
        for expected in (
            "hello",
            "row child",
            "list child",
            "card child",
            "tab content",
            "modal content",
            "Click me",
            "Alice",
            "Vol",
        ):
            assert expected in doc
        # Self-contained: no external src/href (images/video/audio URLs are
        # kept in data-* attributes instead of live src/href).
        externals = re.findall(r'(?:src|href)="https?://[^"]+"', doc)
        assert externals == []

    async def test_renderer_degradation_recorded(self):
        """An unknown/unsupported component degrades to a visible Text
        placeholder and is recorded in metadata['degraded'] — never raises."""
        env = CreateSurface(
            surfaceId="s",
            catalogId="c",
            components=[Component(id="root", component="NotARealComponent", foo="bar")],
            dataModel={},
        )
        art = await SSRHTMLRenderer().render(env)
        doc = art.content.decode()
        assert "not supported" in doc.lower() or "no renderer" in doc.lower()
        assert len(art.metadata["degraded"]) == 1
        record = art.metadata["degraded"][0]
        assert record["component"] == "NotARealComponent"
        assert record["id"] == "root"

    async def test_data_values_are_escaped_no_script_injection(self):
        payload = "<script>alert(1)</script>"
        env = CreateSurface(
            surfaceId="s",
            catalogId="c",
            components=[Component(id="root", component="Text", text=payload)],
            dataModel={},
        )
        art = await SSRHTMLRenderer().render(env)
        doc = art.content.decode()
        assert "<script>alert(1)</script>" not in doc
        assert "&lt;script&gt;" in doc

    async def test_output_has_zero_live_bindings(self):
        env = CreateSurface(
            surfaceId="s",
            catalogId="c",
            components=[Component(id="root", component="Text", text={"path": "/d"})],
            dataModel={"d": "resolved"},
        )
        art = await SSRHTMLRenderer().render(env)
        doc = art.content.decode()
        assert "resolved" in doc
        assert '"path"' not in doc

    async def test_composite_component_still_lowers_and_renders(self):
        """A Parrot composite (KPICard) nested under a primitive Card still
        lowers via its own `.lower()` and renders through the same dispatch."""
        env = CreateSurface(
            surfaceId="s",
            catalogId="c",
            components=[
                Component(id="root", component="Card", child="k1"),
                Component(id="k1", component="KPICard", label="Rev", value=10),
            ],
            dataModel={},
        )
        art = await SSRHTMLRenderer().render(env)
        doc = art.content.decode()
        assert "Rev" in doc and "10" in doc

    async def test_missing_root_yields_empty_body(self):
        env = CreateSurface(
            surfaceId="s",
            catalogId="c",
            components=[Component(id="x", component="Text", text="orphan")],
            dataModel={},
        )
        art = await SSRHTMLRenderer().render(env)
        assert "orphan" not in art.content.decode()

    async def test_deep_links_rendered_as_anchors(self):
        from datetime import datetime, timezone

        from parrot.outputs.a2ui.artifacts import DeepLink

        env = CreateSurface(
            surfaceId="s",
            catalogId="c",
            components=[Component(id="root", component="Text", text="hi")],
            dataModel={},
        )
        link = DeepLink(
            action_label="Open form",
            url="https://resume/x?token=t",
            token_id="t",
            expires_at=datetime.now(timezone.utc),
        )
        art = await SSRHTMLRenderer().render(env, deep_links=[link])
        doc = art.content.decode()
        assert 'href="https://resume/x?token=t"' in doc
        assert art.deep_links[0].token_id == "t"


class TestNewChartTypesDegradation:
    """FEAT-527: gauge/funnel/waterfall/heatmap/treemap have no native visual
    on this static renderer — the type caption still shows the original type
    (``ChartComponent.lower()``'s generic text summary), and each is
    additionally recorded in ``metadata['degraded']`` (never silent)."""

    @pytest.mark.parametrize(
        "chart_type", ["gauge", "funnel", "waterfall", "heatmap", "treemap"]
    )
    async def test_unsupported_chart_type_recorded_as_degraded(self, chart_type):
        env = CreateSurface(
            surfaceId="s", catalogId="c",
            components=[
                Component(
                    id="root", component="Chart", type=chart_type, x="m", y=["v"],
                    data=[{"m": "a", "v": 1}],
                )
            ],
            dataModel={},
        )
        art = await SSRHTMLRenderer().render(env)
        doc = art.content.decode()

        assert f"Chart ({chart_type})" in doc  # caption prints the original type
        assert any(chart_type in d.get("reason", "") for d in art.metadata["degraded"])
        record = next(d for d in art.metadata["degraded"] if d["component"] == "Chart")
        assert record["id"] == "root"

    @pytest.mark.parametrize("chart_type", ["bar", "donut", "radar"])
    async def test_pre_existing_chart_types_not_recorded_as_degraded(self, chart_type):
        env = CreateSurface(
            surfaceId="s", catalogId="c",
            components=[
                Component(
                    id="root", component="Chart", type=chart_type, x="m", y=["v"],
                    data=[{"m": "a", "v": 1}],
                )
            ],
            dataModel={},
        )
        art = await SSRHTMLRenderer().render(env)
        doc = art.content.decode()

        assert f"Chart ({chart_type})" in doc
        assert art.metadata.get("degraded", []) == []


class TestHtmlDocumentDegradesToLink:
    """FEAT-527: ssr-html can never embed HtmlDocument (static renderer) —
    always a titled link (srcUrl) or placeholder text (inline html only),
    always recorded."""

    async def test_htmldocument_degrades_to_link(self):
        env = CreateSurface(
            surfaceId="s", catalogId="c",
            components=[
                Component(id="root", component="HtmlDocument", title="Doc", srcUrl="https://x/infographic-a.html")
            ],
            dataModel={},
        )
        art = await SSRHTMLRenderer().render(env)
        doc = art.content.decode()

        assert '<a href="https://x/infographic-a.html">Doc</a>' in doc
        assert any("HtmlDocument" in d.get("reason", "") for d in art.metadata["degraded"])

    async def test_htmldocument_inline_only_degrades_to_placeholder_text(self):
        env = CreateSurface(
            surfaceId="s", catalogId="c",
            components=[Component(id="root", component="HtmlDocument", title="Doc", html="<p>hi</p>")],
            dataModel={},
        )
        art = await SSRHTMLRenderer().render(env)
        doc = art.content.decode()

        assert "[HTML document: Doc]" in doc
        assert "<a href=" not in doc
        assert any("HtmlDocument" in d.get("reason", "") for d in art.metadata["degraded"])
        # Never echoes the raw HTML.
        assert "<p>hi</p>" not in doc
