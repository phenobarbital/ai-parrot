"""Native/degraded Graph tests across interactive-HTML, SSR-HTML, PDF,
Adaptive Cards, and Folium (FEAT-529 Module 6, TASK-2889)."""

from __future__ import annotations

import pytest

pytest.importorskip("jsonpointer")

from parrot.outputs.a2ui.catalog.viz_core import VIZ_CORE_CATALOG_ID
from parrot.outputs.a2ui.graph import MAX_STATIC_NODES
from parrot.outputs.a2ui.models import Component, CreateSurface
from parrot.outputs.a2ui.renderers import get_a2ui_renderer
from parrot.outputs.a2ui_renderers.adaptive_cards import AdaptiveCardsRenderer
from parrot.outputs.a2ui_renderers.interactive_html import InteractiveHTMLRenderer
from parrot.outputs.a2ui_renderers.pdf import PDFRenderer
from parrot.outputs.a2ui_renderers.ssr_html import SSRHTMLRenderer

pytestmark = pytest.mark.asyncio


def _graph_envelope(**overrides) -> CreateSurface:
    props = {
        "kind": "flowchart",
        "direction": "TB",
        "nodes": [{"id": "a", "label": "Start"}, {"id": "b", "label": "End"}],
        "edges": [{"from": "a", "to": "b", "label": "go"}],
        "accessibleDescription": "A tiny graph.",
    }
    props.update(overrides)
    return CreateSurface(
        surfaceId="main",
        catalogId="https://parrot.dev/catalogs/v1",
        components=[Component(id="root", component="Graph", catalogId=VIZ_CORE_CATALOG_ID, **props)],
    )


def _oversize_envelope() -> CreateSurface:
    nodes = [{"id": f"n{i}"} for i in range(MAX_STATIC_NODES + 1)]
    return CreateSurface(
        surfaceId="main",
        catalogId="https://parrot.dev/catalogs/v1",
        components=[Component(id="root", component="Graph", catalogId=VIZ_CORE_CATALOG_ID, nodes=nodes, edges=[])],
    )


class TestCapabilitiesIncludeVizCore:
    def test_interactive_html_capabilities(self):
        caps = InteractiveHTMLRenderer.capabilities
        assert VIZ_CORE_CATALOG_ID in caps.supported_catalog_ids
        assert "Graph" in caps.supported_components

    def test_ssr_html_capabilities(self):
        caps = SSRHTMLRenderer.capabilities
        assert VIZ_CORE_CATALOG_ID in caps.supported_catalog_ids
        assert "Graph" in caps.supported_components

    def test_pdf_capabilities(self):
        caps = PDFRenderer.capabilities
        assert VIZ_CORE_CATALOG_ID in caps.supported_catalog_ids
        assert "Graph" in caps.supported_components


class TestInteractiveHTMLInterceptsGraph:
    async def test_interactive_html_intercepts_graph(self):
        artifact = await InteractiveHTMLRenderer().render(_graph_envelope())
        doc = artifact.content.decode()
        assert "<svg" in doc
        assert "<details" in doc and "Mermaid source" in doc
        assert "flowchart TB" in doc  # the mermaid source itself
        assert not artifact.metadata.get("degraded")

    async def test_interactive_html_graph_not_viz_core_falls_through(self):
        """A Graph WITHOUT a viz-core catalogId does not intercept — it
        lowers via the standard composite path instead (no SVG emitted)."""
        env = CreateSurface(
            surfaceId="main",
            catalogId="https://parrot.dev/catalogs/v1",
            components=[
                Component(
                    id="root",
                    component="Graph",
                    nodes=[{"id": "a"}, {"id": "b"}],
                    edges=[{"from": "a", "to": "b"}],
                )
            ],
        )
        artifact = await InteractiveHTMLRenderer().render(env)
        assert "<svg" not in artifact.content.decode()

    async def test_resolves_via_registry(self):
        assert get_a2ui_renderer("interactive-html") is InteractiveHTMLRenderer


class TestSSRForceLayoutDegradesToLayered:
    async def test_ssr_force_layout_degrades_to_layered(self):
        env = _graph_envelope(layout={"engine": "force"})
        artifact = await SSRHTMLRenderer().render(env)
        doc = artifact.content.decode()
        assert "<svg" in doc  # still rendered, just with layered positions
        degraded = artifact.metadata.get("degraded") or []
        assert any("force" in d["reason"] for d in degraded)


class TestSSRGraphTooLargeDegrades:
    async def test_ssr_graph_too_large_degrades(self):
        artifact = await SSRHTMLRenderer().render(_oversize_envelope())
        doc = artifact.content.decode()
        assert "<svg" not in doc  # lowered to a truncated edge list instead
        degraded = artifact.metadata.get("degraded") or []
        assert any("static node cap" in d["reason"] for d in degraded)


class TestPdfGraphRendersSvg:
    async def test_pdf_graph_renders_svg(self):
        pytest.importorskip("weasyprint")
        artifact = await PDFRenderer().render(_graph_envelope())
        assert artifact.mime_type == "application/pdf"
        assert artifact.content.startswith(b"%PDF")


class TestAdaptiveCardsDegradesUnsupportedCatalog:
    async def test_adaptive_cards_degrades_unsupported_catalog(self):
        artifact = await AdaptiveCardsRenderer().render(_graph_envelope())
        degraded = artifact.metadata.get("degraded") or []
        assert len(degraded) == 1
        assert degraded[0]["component"] == "Graph"
        assert VIZ_CORE_CATALOG_ID in degraded[0]["reason"]


class TestFoliumDegradesUnsupportedCatalog:
    async def test_folium_degrades_graph_with_catalog_name(self):
        folium = pytest.importorskip("folium")
        del folium
        from parrot.outputs.a2ui_renderers.folium_map import FoliumMapRenderer

        env = CreateSurface(
            surfaceId="main",
            catalogId="https://parrot.dev/catalogs/v1",
            components=[
                Component(id="root", component="Map", layers=[]),
                Component(
                    id="graph",
                    component="Graph",
                    catalogId=VIZ_CORE_CATALOG_ID,
                    nodes=[{"id": "a"}, {"id": "b"}],
                    edges=[{"from": "a", "to": "b"}],
                ),
            ],
        )
        artifact = await FoliumMapRenderer().render(env)
        degraded = artifact.metadata.get("degraded") or []
        graph_records = [d for d in degraded if d["component"] == "Graph"]
        assert len(graph_records) == 1
        assert VIZ_CORE_CATALOG_ID in graph_records[0]["reason"]
