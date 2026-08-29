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
