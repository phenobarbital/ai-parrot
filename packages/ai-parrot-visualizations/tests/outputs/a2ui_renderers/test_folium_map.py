"""Unit tests for the folium map renderer (TASK-1731)."""

import pytest

pytest.importorskip("jsonpointer")
pytest.importorskip("folium")

from parrot.outputs.a2ui.models import Component, CreateSurface
from parrot.outputs.a2ui.renderers import get_a2ui_renderer
from parrot.outputs.a2ui_renderers import folium_map as fm

pytestmark = pytest.mark.asyncio


def _map_envelope() -> CreateSurface:
    return CreateSurface(
        surfaceId="main",
        catalogId="https://parrot.dev/catalogs/v1",
        components=[
            Component(
                id="root",
                component="Map",
                title="Stores",
                layers=[{"name": "stores"}],
                viewport={"center": [40.4, -3.7], "zoom": 6},
                data={"path": "/points"},
            )
        ],
        dataModel={"points": [{"lat": 40.4, "lon": -3.7, "popup": "Madrid"}]},
    )


class TestFoliumMapRenderer:
    async def test_capabilities_declared(self):
        caps = fm.FoliumMapRenderer.capabilities
        assert caps.interactive is False
        assert caps.supports_actions is False
        assert caps.output == "text/html"

    async def test_resolves_via_registry(self):
        assert get_a2ui_renderer("folium_map") is fm.FoliumMapRenderer

    async def test_map_built_from_component_data_only(self):
        art = await fm.FoliumMapRenderer().render(_map_envelope())
        doc = art.content.decode()
        assert art.mime_type == "text/html"
        # Marker coordinates from the baked component data appear in the folium HTML.
        assert "40.4" in doc and "-3.7" in doc

    async def test_deterministic_map_structure(self):
        doc1 = (await fm.FoliumMapRenderer().render(_map_envelope())).content.decode()
        doc2 = (await fm.FoliumMapRenderer().render(_map_envelope())).content.decode()
        # folium embeds random element ids, so compare stable substructure.
        assert doc1.count("L.marker") == doc2.count("L.marker")
        assert "40.4" in doc1 and "40.4" in doc2

    async def test_missing_folium_actionable_error(self, monkeypatch):
        def _boom():
            raise ImportError("no folium")

        monkeypatch.setattr(fm, "_import_folium", _boom)
        with pytest.raises(ImportError) as exc:
            fm._load_folium()
        assert "ai-parrot-visualizations[a2ui,map]" in str(exc.value)

    async def test_no_map_raises(self):
        env = CreateSurface(
            surfaceId="m",
            catalogId="https://parrot.dev/catalogs/v1",
            components=[Component(id="root", component="InfoCard", title="x")],
        )
        with pytest.raises(ValueError):
            await fm.FoliumMapRenderer().render(env)


class TestTASK2544:
    """FEAT-470 TASK-2544: folium_map declares supported_components."""

    async def test_folium_capabilities(self):
        caps = fm.FoliumMapRenderer.capabilities
        assert caps.supported_components == {"Map"}


class TestSiblingDegradationRecorded:
    """Post-review fix: non-Map siblings must not be silently dropped."""

    def _multi_component_envelope(self) -> CreateSurface:
        return CreateSurface(
            surfaceId="main",
            catalogId="https://parrot.dev/catalogs/v1",
            components=[
                Component(
                    id="map-1",
                    component="Map",
                    title="Stores",
                    layers=[{"name": "stores"}],
                    viewport={"center": [40.4, -3.7], "zoom": 6},
                    data=[{"lat": 40.4, "lon": -3.7, "popup": "Madrid"}],
                ),
                Component(id="note-1", component="Text", text="a sibling note"),
            ],
        )

    async def test_sibling_recorded_in_degraded_metadata(self):
        art = await fm.FoliumMapRenderer().render(self._multi_component_envelope())
        degraded = art.metadata.get("degraded", [])
        assert any(d["id"] == "note-1" and d["component"] == "Text" for d in degraded)

    async def test_single_map_no_degradations(self):
        art = await fm.FoliumMapRenderer().render(_map_envelope())
        assert art.metadata.get("degraded", []) == []


class TestBuildMapDocument:
    """FEAT-522 TASK-2786: build_map_document() extraction + MarkerCluster."""

    def test_basic_single_layer(self):
        props = {"layers": [{"layer": "stores", "data": [{"lat": 1.0, "lon": 2.0}]}]}
        document, degradations = fm.build_map_document(props)
        assert b"<html" in document.lower() or b"<!doctype" in document.lower()
        assert degradations == []

    def test_marker_cluster_above_threshold(self):
        points = [{"lat": float(i), "lon": float(i)} for i in range(fm.DEFAULT_CLUSTER_THRESHOLD + 1)]
        props = {"layers": [{"layer": "stores", "data": points}]}
        document, _ = fm.build_map_document(props)
        assert b"markerClusterGroup" in document or b"MarkerCluster" in document

    def test_no_cluster_below_threshold(self):
        points = [{"lat": float(i), "lon": float(i)} for i in range(10)]
        props = {"layers": [{"layer": "stores", "data": points}]}
        document, _ = fm.build_map_document(props)
        assert b"markerClusterGroup" not in document

    def test_per_layer_threshold_override(self):
        points = [{"lat": float(i), "lon": float(i)} for i in range(20)]
        props = {"layers": [{"layer": "stores", "data": points}]}
        document, _ = fm.build_map_document(props, cluster_threshold_by_layer={"stores": 10})
        assert b"markerClusterGroup" in document


class TestBuildMapDocumentOffline:
    """FEAT-522 TASK-2787: offline data-URI swap for folium's default CDN resources."""

    def test_zero_external_cdn_urls(self):
        props = {"layers": [{"layer": "stores", "data": [{"lat": 1.0, "lon": 2.0}]}]}
        document, _ = fm.build_map_document(props)
        text = document.decode("utf-8")
        assert "cdn.jsdelivr.net" not in text
        assert "cdnjs.cloudflare.com" not in text
        assert "code.jquery.com" not in text
        assert "netdna.bootstrapcdn.com" not in text

    def test_data_uris_present(self):
        props = {"layers": [{"layer": "stores", "data": [{"lat": 1.0, "lon": 2.0}]}]}
        document, _ = fm.build_map_document(props)
        text = document.decode("utf-8")
        assert "data:text/javascript;base64," in text
        assert "data:text/css;base64," in text

    def test_build_map_document_zero_network_resources(self):
        """FEAT-522 TASK-2792: spec §4's authoritative version of the offline
        check — introspects the CURRENTLY INSTALLED folium/folium.plugins
        package live (not a hardcoded URL list), so this stays correct even
        if a future folium version changes its exact CDN URLs (Module 6/
        TASK-2791's CI gate is what catches the vendoring falling behind)."""
        import folium
        import folium.plugins as fp

        m = folium.Map()
        mc = fp.MarkerCluster()
        urls = [u for _, u in [*m.default_js, *m.default_css, *mc.default_js, *mc.default_css]]
        assert urls  # sanity: folium actually declares some defaults

        points = [{"lat": float(i), "lon": float(i)} for i in range(fm.DEFAULT_CLUSTER_THRESHOLD + 1)]
        props = {"layers": [{"layer": "stores", "data": points}]}
        document, _ = fm.build_map_document(props)
        text = document.decode("utf-8")
        for url in urls:
            assert url not in text
        # Every corresponding data: URI IS present (both JS and CSS tracks).
        assert "data:text/javascript;base64," in text
        assert "data:text/css;base64," in text

    def test_build_map_document_empty_layers(self):
        """A zero-layer Map renders an empty-state map card, no exception —
        mirrors Chart/DataTable's existing empty-data degradation (spec §7
        Known Risks)."""
        props = {"layers": []}
        document, degradations = fm.build_map_document(props)  # must not raise
        assert document
        assert degradations == []


class TestFoliumMapRendererUnchangedPublicBehavior:
    """FEAT-522 TASK-2792: regression guard on TASK-2786's extraction —
    FoliumMapRenderer.render()'s public signature and RenderedArtifact
    output shape must be byte-for-byte the same fields/structure it had
    before build_map_document() was extracted out of its body."""

    async def test_render_shape_unchanged(self):
        art = await fm.FoliumMapRenderer().render(_map_envelope())

        assert art.artifact_id == f"{fm._SURFACE_NAME}-main"
        assert art.mime_type == "text/html"
        assert isinstance(art.content, bytes)
        assert art.filename == "main.html"
        assert art.title == "Stores"
        assert art.surface == fm._SURFACE_NAME
        assert art.metadata == {}  # no sibling degradations for a single-Map envelope

        # Same field set as before the TASK-2786 extraction — a stray new/
        # removed field would be a public-surface regression.
        assert set(art.model_fields_set) <= {
            "artifact_id",
            "mime_type",
            "content",
            "path",
            "filename",
            "title",
            "surface",
            "source_envelope_ref",
            "deep_links",
            "metadata",
        }


class TestFoliumMapSurfaceOffline:
    """FEAT-522 TASK-2793: closes the SAME offline gap on the standalone
    `folium_map` surface itself (not just the `interactive-html`-embedded
    case, which TestMapDispatch in test_interactive_html.py covers) —
    exercises the full FoliumMapRenderer.render() path end-to-end, not just
    build_map_document() directly (that's TASK-2792's job)."""

    async def test_folium_map_surface_zero_external_resources(self):
        import folium
        import folium.plugins as fp

        m = folium.Map()
        mc = fp.MarkerCluster()
        urls = [u for _, u in [*m.default_js, *m.default_css, *mc.default_js, *mc.default_css]]
        assert urls

        art = await fm.FoliumMapRenderer().render(_map_envelope())
        text = art.content.decode("utf-8")
        for url in urls:
            assert url not in text
        assert "data:text/javascript;base64," in text
        assert "data:text/css;base64," in text
