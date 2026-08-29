"""Tests for FEAT-473 TASK-2563 — StructuredOutputBase._route_envelope dual-emit.

Exercises the satellite hook via the real STRUCTURED_CHART/STRUCTURED_TABLE/
STRUCTURED_MAP renderers (``get_renderer``), asserting the a2ui dual-emit
(``response.a2ui_envelope``, ``out["surfaceId"]``, ``response.artifact_id``)
never disturbs the pre-existing config/data contract and never raises.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest
from parrot.models.outputs import OutputMode, StructuredChartConfig
from parrot.outputs.a2ui.catalog import validate_envelope
from parrot.outputs.a2ui.catalog.base import ProducerOrigin
from parrot.outputs.a2ui.models import A2UIAgentMessage
from parrot.outputs.formats import get_renderer


def _chart_response() -> SimpleNamespace:
    cfg = StructuredChartConfig(type="bar", x="month", y=["sales"], data=[])
    df = pd.DataFrame([{"month": "Jan", "sales": 100}, {"month": "Feb", "sales": 120}])
    # a2ui_envelope/artifact_id default to None on a real AIMessage — set
    # explicitly here since SimpleNamespace has no such defaults.
    return SimpleNamespace(code=None, data=df, output=cfg, response=None, a2ui_envelope=None, artifact_id=None)


@pytest.mark.asyncio
async def test_route_envelope_sets_a2ui_envelope():
    renderer = get_renderer(OutputMode.STRUCTURED_CHART)()
    resp = _chart_response()
    out, _explanation = await renderer.render(resp)

    assert out is not None
    envelope = resp.a2ui_envelope
    assert envelope is not None
    assert envelope["version"] == "v1.0"
    assert out["surfaceId"] == resp.artifact_id
    # validate_message (jsonschema, on the LOWERED form) is exercised by the
    # adapter itself (TASK-2561's own `_validate_wire`, called inside
    # chart_to_surface) — a raw Parrot-catalog message never validates
    # directly (see adapters/structured.py docstring). Here we only assert
    # the hook wired a well-formed, catalog-valid envelope through.
    validate_envelope(A2UIAgentMessage.model_validate(envelope).create_surface, origin=ProducerOrigin.TOOL)


@pytest.mark.asyncio
async def test_route_envelope_never_raises(monkeypatch):
    import parrot.outputs.formats.structured_base as structured_base_mod

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(structured_base_mod, "chart_to_surface", _boom)

    renderer = get_renderer(OutputMode.STRUCTURED_CHART)()
    resp = _chart_response()
    out, _explanation = await renderer.render(resp)

    assert out is not None  # the primary (out, explanation) contract survives
    assert "surfaceId" not in out
    assert resp.a2ui_envelope is None
    assert resp.artifact_id is None


@pytest.mark.asyncio
async def test_output_unchanged_except_surface_id():
    renderer = get_renderer(OutputMode.STRUCTURED_CHART)()
    resp = _chart_response()
    out, _ = await renderer.render(resp)

    pre_feature_dump = resp.output.model_copy(update={"x": "month", "y": ["sales"]}).model_dump(
        mode="json", by_alias=True, exclude={"data"}
    )
    out_minus_surface_id = {k: v for k, v in out.items() if k != "surfaceId"}
    assert out_minus_surface_id == pre_feature_dump
    assert "surfaceId" in out


@pytest.mark.asyncio
async def test_structured_map_multi_layer_envelope():
    from parrot.tools.dataset_manager.spatial import SpatialLayerResult, SpatialResult

    features_a = [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 2]}, "properties": {"name": "A"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [3, 4]}, "properties": {"name": "B"}},
    ]
    features_b = [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [5, 6]}, "properties": {"name": "C"}},
    ]
    spatial_result = SpatialResult(
        layers={
            "schools": SpatialLayerResult(layer="schools", features=features_a, total_count=2, capped=False),
            "malls": SpatialLayerResult(layer="malls", features=features_b, total_count=1, capped=False),
        }
    )

    renderer = get_renderer(OutputMode.STRUCTURED_MAP)()
    resp = MagicMock()
    resp.data = spatial_result
    resp.code = None
    resp.response = "Found schools and malls."
    out, _explanation = await renderer.render(resp)

    assert out is not None
    envelope = resp.a2ui_envelope
    assert envelope is not None
    layers = envelope["createSurface"]["dataModel"]["layers"]
    assert len(layers) == 2
    assert layers[0]["features"] and layers[1]["features"]
    root_props = envelope["createSurface"]["components"][0]
    for i, layer_prop in enumerate(root_props["layers"]):
        assert layer_prop["data"] == {"path": f"/layers/{i}/features"}
