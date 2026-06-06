"""Tests for FEAT-221 TASK-1446: SpatialLayerResult + SpatialResult + as_feature_collection().

Verifies the per-dataset grouping contract and backward-compatible shim.
"""
from __future__ import annotations

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def school_features():
    """Three GeoJSON point features for the 'schools' dataset."""
    return [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-74.0, 40.71]},
            "properties": {"name": "PS 1", "source": "schools"},
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-74.01, 40.72]},
            "properties": {"name": "PS 2", "source": "schools"},
        },
    ]


@pytest.fixture
def mall_features():
    """Two GeoJSON point features for the 'malls' dataset."""
    return [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-73.99, 40.70]},
            "properties": {"name": "Mall A", "source": "malls"},
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
                total_count=5,  # true count > cap → capped
                capped=True,
                geodesic=True,
            ),
            "malls": SpatialLayerResult(
                layer="malls",
                features=mall_features,
                total_count=1,
                capped=False,
                geodesic=False,
            ),
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# Import smoke tests
# ─────────────────────────────────────────────────────────────────────────────


def test_importable():
    """SpatialLayerResult and SpatialResult are importable from the spatial package."""
    from parrot.tools.dataset_manager.spatial import (  # noqa: F401
        SpatialLayerResult,
        SpatialResult,
    )


def test_import_from_contracts():
    """SpatialLayerResult and SpatialResult are importable directly from contracts."""
    from parrot.tools.dataset_manager.spatial.contracts import (  # noqa: F401
        SpatialLayerResult,
        SpatialResult,
    )


# ─────────────────────────────────────────────────────────────────────────────
# SpatialLayerResult unit tests
# ─────────────────────────────────────────────────────────────────────────────


def test_spatial_layer_result_defaults():
    """SpatialLayerResult defaults are sensible."""
    from parrot.tools.dataset_manager.spatial import SpatialLayerResult

    lr = SpatialLayerResult(layer="schools")
    assert lr.features == []
    assert lr.total_count == 0
    assert lr.capped is False
    assert lr.geodesic is True


def test_spatial_layer_result_fields(school_features):
    """SpatialLayerResult stores all fields correctly."""
    from parrot.tools.dataset_manager.spatial import SpatialLayerResult

    lr = SpatialLayerResult(
        layer="schools",
        features=school_features,
        total_count=5,
        capped=True,
        geodesic=False,
    )
    assert lr.layer == "schools"
    assert len(lr.features) == 2
    assert lr.total_count == 5
    assert lr.capped is True
    assert lr.geodesic is False


# ─────────────────────────────────────────────────────────────────────────────
# SpatialResult unit tests
# ─────────────────────────────────────────────────────────────────────────────


def test_spatial_result_version():
    """SpatialResult.version is always 2."""
    from parrot.tools.dataset_manager.spatial import SpatialResult

    res = SpatialResult()
    assert res.version == 2


def test_spatial_result_keyed_per_dataset(two_dataset_spatial_result):
    """SpatialResult is keyed by dataset name."""
    res = two_dataset_spatial_result
    assert set(res.layers.keys()) == {"schools", "malls"}
    assert res.layers["schools"].total_count >= len(res.layers["schools"].features)


def test_spatial_result_per_layer_counts(two_dataset_spatial_result):
    """Each layer has its own total_count and capped flag."""
    res = two_dataset_spatial_result
    assert res.layers["schools"].total_count == 5
    assert res.layers["schools"].capped is True
    assert res.layers["malls"].total_count == 1
    assert res.layers["malls"].capped is False


def test_spatial_result_per_layer_geodesic(two_dataset_spatial_result):
    """Each layer has its own geodesic flag."""
    res = two_dataset_spatial_result
    assert res.layers["schools"].geodesic is True
    assert res.layers["malls"].geodesic is False


# ─────────────────────────────────────────────────────────────────────────────
# as_feature_collection() back-compat tests
# ─────────────────────────────────────────────────────────────────────────────


def test_as_feature_collection_back_compat(two_dataset_spatial_result):
    """as_feature_collection() produces a valid SpatialFeatureCollection."""
    from parrot.tools.dataset_manager.spatial import SpatialFeatureCollection

    fc = two_dataset_spatial_result.as_feature_collection()
    assert isinstance(fc, SpatialFeatureCollection)
    assert fc.type == "FeatureCollection"


def test_as_feature_collection_concatenates_features(two_dataset_spatial_result):
    """as_feature_collection() concatenates all per-layer features."""
    fc = two_dataset_spatial_result.as_feature_collection()
    total_features = sum(
        len(lr.features) for lr in two_dataset_spatial_result.layers.values()
    )
    assert len(fc.features) == total_features


def test_as_feature_collection_sums_total_count(two_dataset_spatial_result):
    """as_feature_collection() sums per-layer total_counts."""
    fc = two_dataset_spatial_result.as_feature_collection()
    expected = sum(lr.total_count for lr in two_dataset_spatial_result.layers.values())
    assert fc.total_count == expected


def test_as_feature_collection_or_capped(two_dataset_spatial_result):
    """as_feature_collection().capped is True when any layer is capped."""
    fc = two_dataset_spatial_result.as_feature_collection()
    # schools is capped=True, so the merged collection should also be capped
    assert fc.capped is True


def test_as_feature_collection_geodesic_paths(two_dataset_spatial_result):
    """as_feature_collection() builds geodesic_paths per dataset."""
    fc = two_dataset_spatial_result.as_feature_collection()
    assert set(fc.geodesic_paths.keys()) == set(two_dataset_spatial_result.layers.keys())
    assert fc.geodesic_paths["schools"] is True
    assert fc.geodesic_paths["malls"] is False


def test_as_feature_collection_empty_result():
    """as_feature_collection() on empty SpatialResult returns empty collection."""
    from parrot.tools.dataset_manager.spatial import SpatialResult

    res = SpatialResult()
    fc = res.as_feature_collection()
    assert fc.features == []
    assert fc.total_count == 0
    assert fc.capped is False
    assert fc.geodesic_paths == {}


def test_as_feature_collection_uncapped():
    """as_feature_collection().capped is False when no layer is capped."""
    from parrot.tools.dataset_manager.spatial import SpatialResult, SpatialLayerResult

    res = SpatialResult(
        layers={
            "dataset_a": SpatialLayerResult(
                layer="dataset_a", features=[], total_count=0, capped=False, geodesic=True
            ),
        }
    )
    fc = res.as_feature_collection()
    assert fc.capped is False
