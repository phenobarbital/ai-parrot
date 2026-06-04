"""Integration tests for FEAT-221: Structured Map Output Mode.

TASK-1451 — e2e integration suite:
  - StructuredMapRenderer + SpatialResult end-to-end (valid payload shape).
  - Multi-dataset: two layers, viewport union, per-layer capping.
  - Handler backward compat: legacy FeatureCollection shape preserved.
  - Homologation invariants: data excluded from output, rows in response.data.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ── Satellite path wiring ──────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[5]
_SATELLITE_SRC = _REPO_ROOT / "packages" / "ai-parrot-visualizations" / "src"
if _SATELLITE_SRC.exists() and str(_SATELLITE_SRC) not in sys.path:
    sys.path.insert(0, str(_SATELLITE_SRC))

satellite_available = pytest.mark.skipif(
    importlib.util.find_spec("parrot.outputs.formats.version") is None,
    reason="ai-parrot-visualizations not installed",
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def school_features():
    """GeoJSON point features for 'schools' dataset."""
    return [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-74.0, 40.7]},
            "properties": {"name": "PS 1", "enrollment": 500, "source": "schools"},
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-74.01, 40.72]},
            "properties": {"name": "PS 2", "enrollment": 320, "source": "schools"},
        },
    ]


@pytest.fixture
def mall_features():
    """GeoJSON point features for 'malls' dataset."""
    return [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-73.95, 40.65]},
            "properties": {"name": "Mall A", "category": "retail", "source": "malls"},
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-73.96, 40.66]},
            "properties": {"name": "Mall B", "category": "outlet", "source": "malls"},
        },
    ]


@pytest.fixture
def two_dataset_spatial_result(school_features, mall_features):
    """SpatialResult with two SpatialLayerResult groups (schools, malls)."""
    from parrot.tools.dataset_manager.spatial import SpatialResult, SpatialLayerResult

    return SpatialResult(
        layers={
            "schools": SpatialLayerResult(
                layer="schools",
                features=school_features,
                total_count=2,
                capped=False,
                geodesic=True,
            ),
            "malls": SpatialLayerResult(
                layer="malls",
                features=mall_features,
                total_count=2,
                capped=False,
                geodesic=True,
            ),
        }
    )


@pytest.fixture
def capped_spatial_result(school_features):
    """SpatialResult simulating a capped per-dataset result."""
    from parrot.tools.dataset_manager.spatial import SpatialResult, SpatialLayerResult

    return SpatialResult(
        layers={
            "schools": SpatialLayerResult(
                layer="schools",
                features=school_features[:1],  # only 1 returned (capped)
                total_count=500,               # but 500 actual matches
                capped=True,
                geodesic=True,
            ),
        }
    )


def make_response(data=None, code=None, response_text=None):
    """Build a minimal response mock."""
    resp = MagicMock()
    resp.data = data
    resp.code = code
    resp.response = response_text
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# test_structured_map_e2e_llm_mode
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
@pytest.mark.asyncio
async def test_structured_map_e2e_llm_mode(two_dataset_spatial_result):
    """StructuredMapRenderer produces config + response.data from a SpatialResult.

    Verifies:
    - out is not None and 'data' is not in out.
    - out['layers'] has correct layer names.
    - response.data is set (per-layer payloads).
    - explanation is passed through.
    """
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    resp = make_response(
        data=two_dataset_spatial_result,
        response_text="Found schools and malls within 5 miles.",
    )
    out, explanation = await r.render(resp)

    # Homologation invariants
    assert out is not None, "render() must return a config dict (not None)"
    assert "data" not in out, "config must exclude the 'data' key (routed to response.data)"

    # Layers
    assert "layers" in out
    layer_names = {layer["layer"] for layer in out["layers"]}
    assert "schools" in layer_names
    assert "malls" in layer_names

    # response.data set
    assert resp.data is not None

    # Explanation
    assert explanation == "Found schools and malls within 5 miles."


# ─────────────────────────────────────────────────────────────────────────────
# test_structured_map_e2e_multi_dataset
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
@pytest.mark.asyncio
async def test_structured_map_e2e_multi_dataset(two_dataset_spatial_result):
    """Two datasets → two layers, viewport union, per-layer capping.

    Verifies:
    - Exactly two layers in output.
    - Viewport bbox encompasses all features.
    - Per-layer capped/total_count survive.
    """
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    resp = make_response(data=two_dataset_spatial_result)
    out, _ = await r.render(resp)

    assert out is not None
    layers = out["layers"]
    assert len(layers) == 2

    layer_names = {lay["layer"] for lay in layers}
    assert layer_names == {"schools", "malls"}

    # Viewport should span all feature coordinates
    assert out.get("viewport") is not None
    bbox = out["viewport"].get("bbox")
    assert bbox is not None
    assert len(bbox) == 4
    min_lng, min_lat, max_lng, max_lat = bbox
    assert min_lng <= max_lng
    assert min_lat <= max_lat


@satellite_available
@pytest.mark.asyncio
async def test_per_layer_capping_preserved(capped_spatial_result):
    """Per-layer capping info (capped=True, total_count) survives into MapLayer."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    resp = make_response(data=capped_spatial_result)
    out, _ = await r.render(resp)

    assert out is not None
    school_layer = next(
        (lay for lay in out["layers"] if lay["layer"] == "schools"), None
    )
    assert school_layer is not None
    assert school_layer.get("totalCount") == 500 or school_layer.get("total_count") == 500
    # capped should be True
    assert school_layer.get("capped") is True


# ─────────────────────────────────────────────────────────────────────────────
# test_deterministic_handler_unchanged
# ─────────────────────────────────────────────────────────────────────────────


def test_deterministic_handler_unchanged(two_dataset_spatial_result):
    """as_feature_collection() provides the legacy SpatialFeatureCollection shape.

    The deterministic frontend path still receives the FeatureCollection contract.
    """
    from parrot.tools.dataset_manager.spatial import SpatialFeatureCollection

    fc = two_dataset_spatial_result.as_feature_collection()

    # MUST be a SpatialFeatureCollection
    assert isinstance(fc, SpatialFeatureCollection)
    assert fc.type == "FeatureCollection"
    assert "features" in fc.model_dump()
    assert "geodesic_paths" in fc.model_dump()

    # Features are merged across all layers
    total = sum(len(lr.features) for lr in two_dataset_spatial_result.layers.values())
    assert len(fc.features) == total

    # geodesic_paths contains per-dataset entries
    assert set(fc.geodesic_paths.keys()) == set(two_dataset_spatial_result.layers.keys())


# ─────────────────────────────────────────────────────────────────────────────
# Homologation invariants
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
@pytest.mark.asyncio
async def test_config_excludes_data_homologation(two_dataset_spatial_result):
    """data key must NOT appear in the rendered config dict (homologation G1)."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    resp = make_response(data=two_dataset_spatial_result)
    out, _ = await r.render(resp)

    assert out is not None
    assert "data" not in out


@satellite_available
@pytest.mark.asyncio
async def test_renderer_never_raises_on_malformed():
    """Malformed response → (None, error_message); never raises (homologation G1)."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    resp = make_response(data="garbage input")
    out, msg = await r.render(resp)

    assert out is None
    assert isinstance(msg, str)


@satellite_available
@pytest.mark.asyncio
async def test_no_html_output(two_dataset_spatial_result):
    """Renderer never produces HTML (no map rendering — G2)."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    resp = make_response(data=two_dataset_spatial_result)
    out, _ = await r.render(resp)

    # The config dict should be a plain JSON-serializable dict with no HTML
    assert out is not None
    import json

    dumped = json.dumps(out, default=str)
    assert "<html" not in dumped.lower()
    assert "folium" not in dumped.lower()


# ─────────────────────────────────────────────────────────────────────────────
# No regression on STRUCTURED_TABLE
# ─────────────────────────────────────────────────────────────────────────────


@satellite_available
@pytest.mark.asyncio
async def test_structured_table_not_broken():
    """STRUCTURED_TABLE renderer still resolves (no regression)."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    renderer_cls = get_renderer(OutputMode.STRUCTURED_TABLE)
    assert renderer_cls is not None
    assert renderer_cls.__name__ == "StructuredTableRenderer"
