"""Unit tests for SpatialResult.from_dataframe (FEAT-224).

Covers the DataFrame -> GeoJSON SpatialResult converter that lets PandasAgent
emit a STRUCTURED_MAP config instead of rendering a Folium map on the backend.

Tests:
    test_latlon_pair_builds_points — lat/lon columns -> GeoJSON Point features.
    test_alias_detection — alternate lat/lon spellings are auto-detected.
    test_geometry_dict_preserved — a geometry column of GeoJSON dicts survives.
    test_geometry_feature_unwrapped — GeoJSON Feature cells are unwrapped.
    test_geo_interface_object — shapely-like __geo_interface__ objects convert.
    test_missing_coords_skipped — rows with NaN/None coords are dropped.
    test_no_geo_columns_raises — indirect-only frames raise ValueError.
    test_geometry_preferred_over_latlon — geometry column wins over lat/lon.
    test_properties_exclude_geo_and_are_jsonable — props drop geo cols, coerce scalars.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from parrot.tools.dataset_manager.spatial.contracts import SpatialResult


def _features(result: SpatialResult, dataset: str = "result") -> list[dict]:
    return result.layers[dataset].features


def test_latlon_pair_builds_points() -> None:
    df = pd.DataFrame(
        {"latitude": [40.4, 41.9], "longitude": [-3.7, 12.5], "city": ["Madrid", "Roma"]}
    )
    result = SpatialResult.from_dataframe(df)
    feats = _features(result)
    assert len(feats) == 2
    # GeoJSON order is [lon, lat].
    assert feats[0]["geometry"] == {"type": "Point", "coordinates": [-3.7, 40.4]}
    assert feats[0]["properties"] == {"city": "Madrid"}
    assert result.layers["result"].total_count == 2


@pytest.mark.parametrize(
    "lat_name,lon_name",
    [("lat", "lon"), ("lat", "lng"), ("latitude", "long")],
)
def test_alias_detection(lat_name: str, lon_name: str) -> None:
    df = pd.DataFrame({lat_name: [1.0], lon_name: [2.0]})
    feats = _features(SpatialResult.from_dataframe(df))
    assert feats[0]["geometry"]["coordinates"] == [2.0, 1.0]


@pytest.mark.parametrize(
    "lat_name,lon_name",
    [
        ("wh_latitude", "wh_longitude"),
        ("store_lat", "store_lng"),
        ("warehouse_lat", "warehouse_long"),
        ("LATITUDE_DEG", "LONGITUDE_DEG"),
    ],
)
def test_prefixed_suffixed_alias_detection(lat_name: str, lon_name: str) -> None:
    """Prefixed/suffixed lat/lon columns are detected by token boundary.

    Regression for the warehouse-map bug: ``wh_latitude``/``wh_longitude`` were
    not recognised by the exact-only alias match, so the converter raised and
    the map could not render.
    """
    df = pd.DataFrame({lat_name: [1.0], lon_name: [2.0], "name": ["A"]})
    feats = _features(SpatialResult.from_dataframe(df))
    assert feats[0]["geometry"]["coordinates"] == [2.0, 1.0]
    # The geo columns become geometry, not properties.
    assert feats[0]["properties"] == {"name": "A"}


def test_token_boundary_avoids_false_positives() -> None:
    """Substring-only matches (``belongings`` -> ``long``) must NOT be treated
    as geo columns; such frames are not mappable and raise."""
    df = pd.DataFrame({"belongings": ["x"], "flat_id": [1], "category": ["c"]})
    with pytest.raises(ValueError):
        SpatialResult.from_dataframe(df)


def test_geometry_dict_preserved() -> None:
    polygon = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
    df = pd.DataFrame({"geometry": [polygon], "name": ["zone"]})
    feats = _features(SpatialResult.from_dataframe(df))
    assert feats[0]["geometry"] == polygon
    assert feats[0]["properties"] == {"name": "zone"}


def test_geometry_feature_unwrapped() -> None:
    feature = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [5.0, 6.0]},
        "properties": {"ignored": True},
    }
    df = pd.DataFrame({"geom": [feature]})
    feats = _features(SpatialResult.from_dataframe(df))
    assert feats[0]["geometry"] == {"type": "Point", "coordinates": [5.0, 6.0]}


def test_geo_interface_object() -> None:
    class _FakeGeom:
        __geo_interface__ = {"type": "Point", "coordinates": [7.0, 8.0]}

    df = pd.DataFrame({"geometry": [_FakeGeom()]})
    feats = _features(SpatialResult.from_dataframe(df))
    assert feats[0]["geometry"] == {"type": "Point", "coordinates": [7.0, 8.0]}


def test_missing_coords_skipped() -> None:
    df = pd.DataFrame({"lat": [40.4, None, np.nan], "lon": [-3.7, 1.0, 2.0]})
    feats = _features(SpatialResult.from_dataframe(df))
    assert len(feats) == 1
    assert feats[0]["geometry"]["coordinates"] == [-3.7, 40.4]


def test_no_geo_columns_raises() -> None:
    df = pd.DataFrame({"city": ["Madrid"], "country": ["ES"]})
    with pytest.raises(ValueError):
        SpatialResult.from_dataframe(df)


def test_geometry_preferred_over_latlon() -> None:
    df = pd.DataFrame(
        {
            "lat": [1.0],
            "lon": [2.0],
            "geometry": [{"type": "Point", "coordinates": [9.0, 9.0]}],
        }
    )
    feats = _features(SpatialResult.from_dataframe(df))
    # Geometry column wins; lat/lon become properties.
    assert feats[0]["geometry"]["coordinates"] == [9.0, 9.0]
    assert feats[0]["properties"] == {"lat": 1.0, "lon": 2.0}


def test_properties_exclude_geo_and_are_jsonable() -> None:
    df = pd.DataFrame(
        {
            "latitude": [40.4],
            "longitude": [-3.7],
            "count": np.array([5], dtype="int64"),
            "when": pd.to_datetime(["2026-06-06"]),
        }
    )
    props = _features(SpatialResult.from_dataframe(df))[0]["properties"]
    assert "latitude" not in props and "longitude" not in props
    # numpy int -> python int; Timestamp -> isoformat string.
    assert props["count"] == 5 and isinstance(props["count"], int)
    assert props["when"].startswith("2026-06-06")


# ---------------------------------------------------------------------------
# PandasAgent._spatial_result_from_dataframe wrapper (FEAT-224)
# Bound to a lightweight stand-in (the method only uses self.logger) so the
# heavy PandasAgent class need not be constructed.
# ---------------------------------------------------------------------------


def _agent_convert(df):
    import logging
    from types import SimpleNamespace

    from parrot.bots.data import PandasAgent

    stub = SimpleNamespace(logger=logging.getLogger("test_from_dataframe"))
    return PandasAgent._spatial_result_from_dataframe(stub, df)


def test_agent_wrapper_returns_result_for_geo_frame() -> None:
    df = pd.DataFrame({"lat": [40.4], "lon": [-3.7], "store": ["A"]})
    result = _agent_convert(df)
    assert result is not None
    assert _features(result)[0]["geometry"]["coordinates"] == [-3.7, 40.4]


def test_agent_wrapper_returns_none_for_indirect_only() -> None:
    # Indirect geo (names, no coords) -> not mappable -> None (skip auto-map).
    df = pd.DataFrame({"city": ["Madrid"], "country": ["ES"]})
    assert _agent_convert(df) is None


def test_agent_wrapper_returns_none_when_no_features_resolved() -> None:
    # Geometry column present but every row missing -> zero features -> None.
    df = pd.DataFrame({"lat": [None], "lon": [None]})
    assert _agent_convert(df) is None
