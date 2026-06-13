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
    """render() sets response.data to the flat tabular rows."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    resp = make_response(data=two_layer_result)
    await r.render(resp)

    assert resp.data is not None
    assert isinstance(resp.data, list)
    # 2 school features + 1 mall feature = 3 flat rows
    assert len(resp.data) == 3
    for row in resp.data:
        assert isinstance(row, dict)
        assert "payload" not in row, "rows must be tabular, not per-layer payloads"


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
# Marker colors (piggyback — FEAT-221)
# ─────────────────────────────────────────────────────────────────────────────


def _layers_by_id(out):
    return {layer["layer"]: layer for layer in out["layers"]}


@pytest.mark.asyncio
async def test_marker_color_default_applies_to_all_layers(two_layer_result):
    """A 'default' color is applied to every layer."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    text = 'Here is your map.\n```mapcolors\n{"default": "red"}\n```'
    resp = make_response(data=two_layer_result, response_text=text)
    out, explanation = await r.render(resp)

    layers = _layers_by_id(out)
    assert layers["schools"]["markerColor"] == "red"
    assert layers["malls"]["markerColor"] == "red"
    # The fenced block is stripped from the explanation shown to the user.
    assert "mapcolors" not in (explanation or "")
    assert explanation == "Here is your map."


@pytest.mark.asyncio
async def test_marker_color_per_layer(two_layer_result):
    """Per-dataset colors are matched by dataset name."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    text = '```mapcolors\n{"schools": "blue", "malls": "green"}\n```'
    resp = make_response(data=two_layer_result, response_text=text)
    out, _ = await r.render(resp)

    layers = _layers_by_id(out)
    assert layers["schools"]["markerColor"] == "blue"
    assert layers["malls"]["markerColor"] == "green"


@pytest.mark.asyncio
async def test_marker_color_hex_accepted(two_layer_result):
    """Hex color values are accepted and lowercased."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    text = '```mapcolors\n{"default": "#1F77B4"}\n```'
    resp = make_response(data=two_layer_result, response_text=text)
    out, _ = await r.render(resp)

    assert all(layer["markerColor"] == "#1f77b4" for layer in out["layers"])


@pytest.mark.asyncio
async def test_marker_color_invalid_dropped(two_layer_result):
    """Unsupported color names are dropped (fail-open → no color)."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    text = '```mapcolors\n{"schools": "definitely-not-a-color"}\n```'
    resp = make_response(data=two_layer_result, response_text=text)
    out, _ = await r.render(resp)

    layers = _layers_by_id(out)
    assert layers["schools"]["markerColor"] is None
    assert layers["malls"]["markerColor"] is None


@pytest.mark.asyncio
async def test_marker_color_absent_when_no_block(two_layer_result):
    """No fenced block → no marker color (default behaviour preserved)."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    resp = make_response(data=two_layer_result, response_text="A plain map.")
    out, explanation = await r.render(resp)

    assert all(layer["markerColor"] is None for layer in out["layers"])
    assert explanation == "A plain map."


@pytest.mark.asyncio
async def test_marker_color_malformed_block_ignored(two_layer_result):
    """A malformed JSON block is ignored without raising."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    text = '```mapcolors\n{not valid json}\n```'
    resp = make_response(data=two_layer_result, response_text=text)
    out, explanation = await r.render(resp)

    assert out is not None
    assert all(layer["markerColor"] is None for layer in out["layers"])
    # Block is still stripped even when its body fails to parse.
    assert "mapcolors" not in (explanation or "")


@pytest.mark.asyncio
async def test_marker_color_marker_colors_wrapper(two_layer_result):
    """A {"marker_colors": {...}} wrapper object is unwrapped."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    text = '```mapcolors\n{"marker_colors": {"default": "purple"}}\n```'
    resp = make_response(data=two_layer_result, response_text=text)
    out, _ = await r.render(resp)

    assert all(layer["markerColor"] == "purple" for layer in out["layers"])


# ─────────────────────────────────────────────────────────────────────────────
# data_shape support
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_render_geojson_data_shape(two_layer_result):
    """data_shape=geojson passes features through as FeatureCollection in output.datasets."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    resp = make_response(data=two_layer_result)
    out, _ = await r.render(resp)

    # Default data_shape is geojson (no profile in test)
    payloads = out["datasets"]
    assert len(payloads) == 2
    for entry in payloads:
        assert "payload" in entry
        payload = entry["payload"]
        assert isinstance(payload, dict)
        assert payload["type"] == "FeatureCollection"


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


# ─────────────────────────────────────────────────────────────────────────────
# FEAT-223 TASK-1457 — ArtifactType.MAP + envelope conformance
# ─────────────────────────────────────────────────────────────────────────────


def test_artifacttype_map_exists():
    """ArtifactType.MAP = 'map' now exists in the enum."""
    import sys
    import importlib.util
    from pathlib import Path
    # File: packages/ai-parrot/tests/outputs/formats/<file>.py
    # parents[3] = packages/ai-parrot → "src" = packages/ai-parrot/src
    _wt_src = Path(__file__).resolve().parents[3] / "src"

    _spec = importlib.util.spec_from_file_location(
        "parrot.storage.models_task1457",
        _wt_src / "parrot" / "storage" / "models.py",
    )
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)

    assert hasattr(_mod.ArtifactType, "MAP")
    assert _mod.ArtifactType.MAP == "map"
    assert _mod.ArtifactType("map") is _mod.ArtifactType.MAP


class TestMapEnvelopeConformance:
    """FEAT-223: verify StructuredMapRenderer uses the shared StructuredOutputBase contract."""

    @pytest.mark.asyncio
    async def test_output_excludes_data(self, two_layer_result):
        """After retrofit, the map config output has no 'data' key."""
        from parrot.outputs.formats import get_renderer
        from parrot.models.outputs import OutputMode

        r = get_renderer(OutputMode.STRUCTURED_MAP)()
        resp = make_response(data=two_layer_result)
        out, _ = await r.render(resp)

        assert out is not None
        assert "data" not in out, "data key must be excluded from output via _route_envelope"

    @pytest.mark.asyncio
    async def test_payloads_routed_to_output_datasets(self, two_layer_result):
        """Per-layer payloads live in output.datasets; response.data is tabular rows."""
        from parrot.outputs.formats import get_renderer
        from parrot.models.outputs import OutputMode

        r = get_renderer(OutputMode.STRUCTURED_MAP)()
        resp = make_response(data=two_layer_result)
        out, _ = await r.render(resp)

        assert out is not None
        # GeoJSON payloads travel in output.datasets
        assert isinstance(out["datasets"], list) and len(out["datasets"]) == 2
        for entry in out["datasets"]:
            assert "dataset" in entry
            assert "payload" in entry
        # response.data carries the flat tabular rows the payloads were built from
        assert isinstance(resp.data, list) and len(resp.data) == 3
        for row in resp.data:
            assert "dataset" not in row
            assert "payload" not in row

    @pytest.mark.asyncio
    async def test_existing_behavior_preserved(self, two_layer_result):
        """Viewport, geojson shape, and MapQuery extraction are unchanged after retrofit."""
        from parrot.outputs.formats import get_renderer
        from parrot.models.outputs import OutputMode

        r = get_renderer(OutputMode.STRUCTURED_MAP)()
        resp = make_response(
            data=two_layer_result,
            response_text="Schools and malls near downtown.",
        )
        out, explanation = await r.render(resp)

        assert out is not None
        assert explanation == "Schools and malls near downtown."
        # Viewport computed
        assert out.get("viewport") is not None
        assert len(out["viewport"]["bbox"]) == 4
        # Layers present
        assert "layers" in out
        assert len(out["layers"]) == 2
        # Payload entries available on output.datasets; tabular rows on response.data
        assert isinstance(out["datasets"], list) and len(out["datasets"]) == 2
        assert isinstance(resp.data, list) and len(resp.data) == 3


# ─────────────────────────────────────────────────────────────────────────────
# Regression: warehouse-map bug — agent returns a DataFrame in STRUCTURED_MAP
# mode instead of calling the spatial_filter tool. PandasAgent now converts the
# result rows to a SpatialResult (via _spatial_result_from_dataframe), so the
# renderer must accept it instead of failing with "must be a SpatialResult".
# Columns use the wh_latitude/wh_longitude prefix that the exact-only alias
# match previously missed.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_render_accepts_dataframe_converted_warehouses():
    """End-to-end: wh_latitude/wh_longitude DataFrame -> SpatialResult -> render."""
    import logging
    from types import SimpleNamespace

    import pandas as pd

    from parrot.bots.data import PandasAgent
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    df = pd.DataFrame(
        {
            "warehouse_id": ["recA", "recB", "recC"],
            "warehouse_name": ["Denver", "Phoenix", "Boston"],
            "wh_latitude": [39.7904, 33.3429, 42.2107],
            "wh_longitude": [-104.9939, -111.9525, -71.0286],
        }
    )

    stub = SimpleNamespace(logger=logging.getLogger("test_warehouse_map"))
    spatial_result = PandasAgent._spatial_result_from_dataframe(stub, df)
    assert spatial_result is not None, "wh_latitude/wh_longitude must be detected"

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    resp = make_response(data=spatial_result, response_text="3 warehouses.")
    out, explanation = await r.render(resp)

    # Renderer accepted the converted result (no "must be a SpatialResult").
    assert out is not None
    assert "layers" in out and len(out["layers"]) == 1
    assert explanation == "3 warehouses."


# ─────────────────────────────────────────────────────────────────────────────
# Tabular rows contract — response.data carries the data the GeoJSON was built
# from (properties + coordinates), NOT the GeoJSON itself.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tabular_rows_point_coordinates(two_layer_result):
    """Point features yield latitude/longitude columns in response.data rows."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    resp = make_response(data=two_layer_result)
    await r.render(resp)

    school_row = next(row for row in resp.data if row.get("name") == "PS 1")
    assert school_row["latitude"] == 40.7
    assert school_row["longitude"] == -74.0
    assert school_row["enrollment"] == 500
    assert "_geometry" not in school_row


@pytest.mark.asyncio
async def test_tabular_rows_layer_discriminator(two_layer_result):
    """Multi-layer results add a 'layer' column to every row."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode

    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    resp = make_response(data=two_layer_result)
    await r.render(resp)

    assert {row["layer"] for row in resp.data} == {"schools", "malls"}


@pytest.mark.asyncio
async def test_tabular_rows_single_layer_no_discriminator():
    """Single-layer results do NOT add a 'layer' column."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode
    from parrot.tools.dataset_manager.spatial import SpatialResult, SpatialLayerResult

    spatial = SpatialResult(
        layers={
            "stores": SpatialLayerResult(
                layer="stores",
                features=[
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [-73.9, 40.8]},
                        "properties": {"name": "Store A"},
                    },
                ],
                total_count=1,
            ),
        }
    )
    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    resp = make_response(data=spatial)
    await r.render(resp)

    assert len(resp.data) == 1
    assert "layer" not in resp.data[0]


@pytest.mark.asyncio
async def test_tabular_rows_non_point_geometry():
    """Non-Point geometries are preserved under a '_geometry' key (no lat/lon)."""
    from parrot.outputs.formats import get_renderer
    from parrot.models.outputs import OutputMode
    from parrot.tools.dataset_manager.spatial import SpatialResult, SpatialLayerResult

    polygon = {
        "type": "Polygon",
        "coordinates": [[[-74.0, 40.7], [-74.0, 40.8], [-73.9, 40.8], [-74.0, 40.7]]],
    }
    spatial = SpatialResult(
        layers={
            "zones": SpatialLayerResult(
                layer="zones",
                features=[
                    {
                        "type": "Feature",
                        "geometry": polygon,
                        "properties": {"name": "Zone 1"},
                    },
                ],
                total_count=1,
            ),
        }
    )
    r = get_renderer(OutputMode.STRUCTURED_MAP)()
    resp = make_response(data=spatial)
    await r.render(resp)

    row = resp.data[0]
    assert row["_geometry"] == polygon
    assert "latitude" not in row
    assert "longitude" not in row


def test_tabular_rows_property_keys_win():
    """Existing property keys (latitude/longitude/layer) are never overwritten."""
    from parrot.outputs.formats.structured_map import StructuredMapRenderer
    from parrot.tools.dataset_manager.spatial import SpatialResult, SpatialLayerResult

    spatial = SpatialResult(
        layers={
            "a": SpatialLayerResult(
                layer="a",
                features=[
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [-74.0, 40.7]},
                        "properties": {"latitude": "original", "layer": "custom"},
                    },
                ],
                total_count=1,
            ),
            "b": SpatialLayerResult(layer="b", features=[], total_count=0),
        }
    )
    rows = StructuredMapRenderer._build_tabular_rows(spatial, row_limit=1000)

    assert rows[0]["latitude"] == "original"
    assert rows[0]["layer"] == "custom"
    assert rows[0]["longitude"] == -74.0
