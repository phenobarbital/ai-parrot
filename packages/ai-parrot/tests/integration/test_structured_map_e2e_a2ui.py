"""FEAT-473 TASK-2566 — STRUCTURED_MAP end-to-end A2UI conformance.

NOTE: named ``..._e2e_a2ui.py`` (not ``..._e2e.py``) to avoid colliding with
the pre-existing FEAT-221 ``test_structured_map_e2e.py`` in this same
directory — the task's own file table named the latter, unaware it was
already taken; see this task's Completion Note.

Multi-dataset spatial result → the satellite hook's dual-emit produces a
v1.0 envelope whose ``Map`` layers each bind ``/layers/<i>/features``, and
``FoliumMapRenderer`` (satellite A2UI renderer) renders an HTML document
containing one ``FeatureGroup`` per layer.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[5]
_SATELLITE_SRC = _REPO_ROOT / "packages" / "ai-parrot-visualizations" / "src"
if _SATELLITE_SRC.exists() and str(_SATELLITE_SRC) not in sys.path:
    sys.path.insert(0, str(_SATELLITE_SRC))

pytest.importorskip("jsonpointer")
pytest.importorskip("folium")


@pytest.mark.asyncio
async def test_structured_map_e2e_a2ui():
    from parrot.models.outputs import OutputMode
    from parrot.outputs.a2ui.models import A2UIAgentMessage
    from parrot.outputs.a2ui_renderers.folium_map import FoliumMapRenderer
    from parrot.outputs.formats import get_renderer
    from parrot.tools.dataset_manager.spatial import SpatialLayerResult, SpatialResult

    school_features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-74.0, 40.7]},
            "properties": {"name": "PS 1"},
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-74.01, 40.72]},
            "properties": {"name": "PS 2"},
        },
    ]
    mall_features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-73.99, 40.70]},
            "properties": {"name": "Mall A"},
        },
    ]
    spatial_result = SpatialResult(
        layers={
            "schools": SpatialLayerResult(layer="schools", features=school_features, total_count=2, capped=False),
            "malls": SpatialLayerResult(layer="malls", features=mall_features, total_count=1, capped=False),
        }
    )

    resp = MagicMock()
    resp.data = spatial_result
    resp.code = None
    resp.response = "Found schools and malls."
    resp.a2ui_envelope = None
    resp.artifact_id = None

    renderer = get_renderer(OutputMode.STRUCTURED_MAP)()
    out, _explanation = await renderer.render(resp)

    assert out is not None
    assert "data" not in out

    envelope = resp.a2ui_envelope
    assert envelope is not None
    surface = A2UIAgentMessage.model_validate(envelope).create_surface
    root = next(c for c in surface.components if c.id == "root")
    assert root.component == "Map"
    assert len(root.model_extra["layers"]) == 2
    for i, layer in enumerate(root.model_extra["layers"]):
        assert layer["data"] == {"path": f"/layers/{i}/features"}

    # FoliumMapRenderer (satellite A2UI renderer) renders one FeatureGroup/layer.
    artifact = await FoliumMapRenderer().render(surface)
    doc = artifact.content.decode()
    assert artifact.mime_type == "text/html"
    assert doc.count("L.featureGroup(") == 2
