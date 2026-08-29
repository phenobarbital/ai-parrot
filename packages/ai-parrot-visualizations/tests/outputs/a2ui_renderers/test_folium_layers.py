"""Tests for FEAT-473 TASK-2564 — FoliumMapRenderer multi-layer prop fidelity."""

import pytest

pytest.importorskip("jsonpointer")
pytest.importorskip("folium")

from parrot.outputs.a2ui.models import Component, CreateSurface
from parrot.outputs.a2ui_renderers import folium_map as fm

pytestmark = pytest.mark.asyncio


def _multi_layer_envelope() -> CreateSurface:
    return CreateSurface(
        surfaceId="main",
        catalogId="https://parrot.dev/catalogs/v1",
        components=[
            Component(
                id="root",
                component="Map",
                title="Stores",
                layers=[
                    {
                        "layer": "schools",
                        "markerColor": "red",
                        "labelField": "name",
                        "tooltipTemplate": "{name} ({enrollment})",
                        "data": {"path": "/layers/0/features"},
                    },
                    {
                        "layer": "malls",
                        "markerColor": "#00ff00",
                        "data": {"path": "/layers/1/features"},
                    },
                ],
                viewport={"center": [40.4, -3.7], "zoom": 6},
            )
        ],
        dataModel={
            "layers": [
                {
                    "features": [
                        {
                            "name": "PS 1",
                            "enrollment": 500,
                            "_geometry": {"type": "Point", "coordinates": [-74.0, 40.7]},
                        }
                    ]
                },
                {"features": [{"name": "Mall A", "_geometry": {"type": "Point", "coordinates": [-73.99, 40.70]}}]},
            ]
        },
    )


def _geodesic_envelope() -> CreateSurface:
    return CreateSurface(
        surfaceId="main",
        catalogId="https://parrot.dev/catalogs/v1",
        components=[
            Component(
                id="root",
                component="Map",
                title="Routes",
                layers=[{"layer": "routes", "geodesic": True, "data": {"path": "/layers/0/features"}}],
                viewport={"center": [40.4, -3.7], "zoom": 6},
            )
        ],
        dataModel={
            "layers": [
                {
                    "features": [
                        {
                            "_geometry": {
                                "type": "LineString",
                                "coordinates": [[-74.0, 40.7], [-73.9, 40.8]],
                            }
                        }
                    ]
                }
            ]
        },
    )


async def test_folium_multi_layer_and_marker_color():
    art = await fm.FoliumMapRenderer().render(_multi_layer_envelope())
    doc = art.content.decode()

    assert doc.count("L.featureGroup(") == 2
    assert doc.count("L.circleMarker") == 2
    assert "PS 1 (500)" in doc  # tooltipTemplate applied
    assert "40.7" in doc and "40.7" in doc


async def test_folium_geodesic_polyline():
    art = await fm.FoliumMapRenderer().render(_geodesic_envelope())
    doc = art.content.decode()

    assert "L.polyline" in doc
    assert doc.count("L.marker") == 0


async def test_folium_legacy_single_layer_still_renders(monkeypatch):
    """Envelopes without per-layer `data` (pre-FEAT-473) use the legacy single-layer path."""
    env = CreateSurface(
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
    art = await fm.FoliumMapRenderer().render(env)
    doc = art.content.decode()
    assert "40.4" in doc and "-3.7" in doc
    assert doc.count("L.marker") == 1
