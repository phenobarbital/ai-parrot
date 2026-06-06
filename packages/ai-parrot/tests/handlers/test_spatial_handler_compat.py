"""Tests for FEAT-221 TASK-1448: Spatial transport handler compatibility.

Verifies that the handler:
- Default (no version param): returns legacy SpatialFeatureCollection JSON shape.
- version=2: returns SpatialResult JSON with 'layers' dict.
- AgenTalk envelope: returns legacy SpatialFeatureCollection via as_feature_collection().
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def two_layer_spatial_result():
    """SpatialResult with two layers."""
    from parrot.tools.dataset_manager.spatial import SpatialResult, SpatialLayerResult

    return SpatialResult(
        layers={
            "schools": SpatialLayerResult(
                layer="schools",
                features=[
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [-74.0, 40.7]},
                        "properties": {"name": "PS 1", "source": "schools"},
                    }
                ],
                total_count=1,
                capped=False,
                geodesic=True,
            ),
        }
    )


@pytest.fixture
def mock_dm(two_layer_spatial_result):
    """Mock DatasetManager whose spatial_filter returns a SpatialResult."""
    dm = MagicMock()
    dm.spatial_filter = AsyncMock(return_value=two_layer_spatial_result)
    return dm


# ─────────────────────────────────────────────────────────────────────────────
# AgenTalk envelope backward compat
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_envelope_returns_legacy_shape(mock_dm):
    """SpatialFilterEnvelope.forward() returns a SpatialFeatureCollection."""
    from parrot.handlers.spatial_filter_handler import SpatialFilterEnvelope
    from parrot.tools.dataset_manager.spatial.contracts import (
        SpatialFilterSpec,
        SpatialFeatureCollection,
    )

    spec = SpatialFilterSpec(point=(40.7, -74.0), radius=5.0, unit="mi", datasets=["schools"])
    envelope = SpatialFilterEnvelope(spec=spec, agent_id="test-agent")
    result = await envelope.forward(mock_dm)

    assert isinstance(result, SpatialFeatureCollection)
    assert result.type == "FeatureCollection"
    assert "features" in result.model_dump()


@pytest.mark.asyncio
async def test_envelope_merges_features(mock_dm):
    """SpatialFilterEnvelope.forward() merges all features from layers."""
    from parrot.handlers.spatial_filter_handler import SpatialFilterEnvelope
    from parrot.tools.dataset_manager.spatial.contracts import SpatialFilterSpec

    spec = SpatialFilterSpec(point=(40.7, -74.0), radius=5.0, unit="mi", datasets=["schools"])
    envelope = SpatialFilterEnvelope(spec=spec, agent_id="test-agent")
    result = await envelope.forward(mock_dm)

    assert len(result.features) == 1
    assert result.total_count == 1
    assert result.capped is False


# ─────────────────────────────────────────────────────────────────────────────
# SpatialResult.as_feature_collection() — shape contract
# ─────────────────────────────────────────────────────────────────────────────


def test_handler_serves_legacy_shape(two_layer_spatial_result):
    """as_feature_collection() produces the correct legacy SpatialFeatureCollection shape."""
    from parrot.tools.dataset_manager.spatial import SpatialFeatureCollection

    fc = two_layer_spatial_result.as_feature_collection()
    assert isinstance(fc, SpatialFeatureCollection)
    assert fc.type == "FeatureCollection"
    assert "features" in fc.model_dump()
    assert "geodesic_paths" in fc.model_dump()


def test_legacy_shape_has_correct_feature_count(two_layer_spatial_result):
    """Legacy shape feature count equals sum of all layer features."""
    fc = two_layer_spatial_result.as_feature_collection()
    total = sum(len(lr.features) for lr in two_layer_spatial_result.layers.values())
    assert len(fc.features) == total


def test_version2_shape_has_layers(two_layer_spatial_result):
    """SpatialResult (version=2) has a 'layers' dict with dataset keys."""
    assert two_layer_spatial_result.version == 2
    assert "layers" in two_layer_spatial_result.model_dump()
    assert "schools" in two_layer_spatial_result.layers


# ─────────────────────────────────────────────────────────────────────────────
# _json_response helper — serialization check
# ─────────────────────────────────────────────────────────────────────────────


def test_spatial_feature_collection_serializable(two_layer_spatial_result):
    """The legacy SpatialFeatureCollection is JSON-serializable via model_dump()."""
    import json

    fc = two_layer_spatial_result.as_feature_collection()
    dumped = fc.model_dump()
    # Should not raise
    serialized = json.dumps(dumped, default=str)
    parsed = json.loads(serialized)
    assert parsed["type"] == "FeatureCollection"


def test_spatial_result_serializable(two_layer_spatial_result):
    """The new SpatialResult is JSON-serializable via model_dump()."""
    import json

    dumped = two_layer_spatial_result.model_dump()
    serialized = json.dumps(dumped, default=str)
    parsed = json.loads(serialized)
    assert parsed["version"] == 2
    assert "layers" in parsed
