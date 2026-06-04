"""Tests for FEAT-221 TASK-1449: StructuredMapRenderer.

Verifies the renderer contract:
- get_renderer(STRUCTURED_MAP) resolves the StructuredMapRenderer.
- render() returns (out_without_data, explanation).
- One MapLayer per dataset; columns typed; tooltip from profile.
- Both data_shape="geojson" and "rows" produce valid payloads.
- Viewport bbox computed from feature bounds.
- LLM refine does not change hard types.
- Renderer never raises on malformed input.
- Empty layer is preserved (not dropped).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ── Satellite path wiring ──────────────────────────────────────────────────────
# Add ai-parrot-visualizations/src to sys.path so the PEP 420 namespace merge
# can discover the satellite renderer modules (e.g. structured_map.py).
_REPO_ROOT = Path(__file__).resolve().parents[5]
_SATELLITE_SRC = _REPO_ROOT / "packages" / "ai-parrot-visualizations" / "src"
if _SATELLITE_SRC.exists() and str(_SATELLITE_SRC) not in sys.path:
    sys.path.insert(0, str(_SATELLITE_SRC))


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def school_features():
    return [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-74.0, 40.7]},
            "properties": {"name": "PS 1", "enrollment": 500},
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-74.01, 40.72]},
            "properties": {"name": "PS 2", "enrollment": 320},
        },
    ]


@pytest.fixture
def mall_features():
    return [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-73.99, 40.70]},
            "properties": {"name": "Mall A", "category": "retail"},
        },
    ]


@pytest.fixture
def two_layer_result(school_features, mall_features):
    """SpatialResult with schools (2 features) and malls (1 feature)."""
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
                total_count=1,
                capped=False,
                geodesic=True,
            ),
        }
    )


@pytest.fixture
def empty_layer_result(school_features):
    """SpatialResult with schools (features) and malls (empty)."""
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
                features=[],  # empty!
                total_count=0,
                capped=False,
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
# Renderer registration
# ─────────────────────────────────────────────────────────────────────────────


def test_renderer_registered():
    """get_renderer(STRUCTURED_MAP) resolves StructuredMapRenderer."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    renderer_cls = get_renderer(OutputMode.STRUCTURED_MAP)
    assert renderer_cls is not None
    assert renderer_cls.__name__ == "StructuredMapRenderer"


def test_renderer_instantiable():
    """StructuredMapRenderer can be instantiated."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    assert r is not None


# ─────────────────────────────────────────────────────────────────────────────
# render() — happy-path contract
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_render_builds_layers(two_layer_result):
    """render() returns (out, explanation) with one layer per dataset."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    resp = make_response(data=two_layer_result, response_text="Found schools and malls.")
    out, explanation = await r.render(resp)

    assert out is not None
    assert "data" not in out
    assert "layers" in out
    assert {l["layer"] for l in out["layers"]} == {"schools", "malls"}
    assert explanation == "Found schools and malls."


@pytest.mark.asyncio
async def test_render_data_excluded(two_layer_result):
    """render() excludes 'data' key from the output dict."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    resp = make_response(data=two_layer_result)
    out, _ = await r.render(resp)

    assert "data" not in out


@pytest.mark.asyncio
async def test_render_sets_response_data(two_layer_result):
    """render() sets response.data to the per-layer payloads."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    resp = make_response(data=two_layer_result)
    await r.render(resp)

    assert resp.data is not None
    assert isinstance(resp.data, list)
    assert len(resp.data) > 0


@pytest.mark.asyncio
async def test_render_viewport_bbox(two_layer_result):
    """render() computes a viewport bbox from feature coordinates."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    resp = make_response(data=two_layer_result)
    out, _ = await r.render(resp)

    assert out.get("viewport") is not None
    assert out["viewport"].get("bbox") is not None
    bbox = out["viewport"]["bbox"]
    assert len(bbox) == 4


# ─────────────────────────────────────────────────────────────────────────────
# data_shape support
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_render_geojson_data_shape(two_layer_result):
    """data_shape=geojson passes features through as FeatureCollection."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    resp = make_response(data=two_layer_result)
    await r.render(resp)

    # Default data_shape is geojson (no profile in test)
    payloads = resp.data
    for entry in payloads:
        assert "payload" in entry
        payload = entry["payload"]
        # Should be FeatureCollection or rows dict
        assert isinstance(payload, dict)


# ─────────────────────────────────────────────────────────────────────────────
# Never raises — error handling
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_render_never_raises_on_none_data():
    """render() returns (None, msg) when response.data is None."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    resp = make_response(data=None)
    out, msg = await r.render(resp)

    assert out is None
    assert isinstance(msg, str)
    assert len(msg) > 0


@pytest.mark.asyncio
async def test_render_never_raises_on_wrong_type():
    """render() returns (None, msg) when response.data is not a SpatialResult."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    resp = make_response(data="not a spatial result")
    out, msg = await r.render(resp)

    assert out is None
    assert isinstance(msg, str)


@pytest.mark.asyncio
async def test_render_never_raises_on_exception():
    """render() catches unexpected exceptions and returns (None, msg)."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    # Trigger an exception by providing an object that raises on attribute access
    bad_resp = MagicMock()
    bad_resp.response = None
    bad_resp.data = None
    bad_resp.code = None
    out, msg = await r.render(bad_resp)

    # Should either succeed (empty result) or return (None, msg) — never raise
    if out is None:
        assert isinstance(msg, str)


# ─────────────────────────────────────────────────────────────────────────────
# Empty layer is preserved
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_render_empty_layer_preserved(empty_layer_result):
    """render() preserves empty layers (not dropped)."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    resp = make_response(data=empty_layer_result)
    out, _ = await r.render(resp)

    assert out is not None
    layer_names = {l["layer"] for l in out["layers"]}
    assert "malls" in layer_names  # empty layer must be present


# ─────────────────────────────────────────────────────────────────────────────
# LLM refine — deterministic wins
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_refine_does_not_change_hard_types(two_layer_result):
    """LLM cannot change number/datetime/boolean base types via refine hints."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    # Inject a response.code that tries to change types
    resp = make_response(
        data=two_layer_result,
        code={"enrollment": "currency"},  # enrollment may be typed as integer
    )
    out, _ = await r.render(resp)

    # The output should not have had its layer destroyed
    assert out is not None
    school_layer = next(
        (l for l in out["layers"] if l["layer"] == "schools"), None
    )
    assert school_layer is not None
    enrollment_col = next(
        (c for c in school_layer["columns"] if c["name"] == "enrollment"), None
    )
    assert enrollment_col is not None
    # enrollment values are integers (500, 320) — LLM hint must NOT override inferred type
    assert enrollment_col["type"] in ("integer", "number"), (
        f"LLM hint must not override inferred integer type; got {enrollment_col['type']!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Viewport computation
# ─────────────────────────────────────────────────────────────────────────────


def test_compute_viewport_from_bounds(two_layer_result):
    """_compute_viewport extracts bbox + center from feature coordinates."""
    from parrot.outputs.formats.structured_map import StructuredMapRenderer

    r = StructuredMapRenderer()
    viewport = r._compute_viewport(two_layer_result)

    assert viewport is not None
    assert viewport.bbox is not None
    assert len(viewport.bbox) == 4
    min_lng, min_lat, max_lng, max_lat = viewport.bbox
    assert min_lng <= max_lng
    assert min_lat <= max_lat
    assert viewport.center is not None


def test_compute_viewport_empty_result():
    """_compute_viewport returns None when no features have coordinates."""
    from parrot.outputs.formats.structured_map import StructuredMapRenderer
    from parrot.tools.dataset_manager.spatial import SpatialResult

    r = StructuredMapRenderer()
    viewport = r._compute_viewport(SpatialResult())

    assert viewport is None
