"""Unit tests for FEAT-219 Module 1: spatial contracts + profile registry + manifest.

Tests:
    test_spec_roundtrip — SpatialFilterSpec validates units/point; rejects malformed.
    test_profile_registry_validates_dataset — Resolving an unknown dataset raises ValueError.
    test_manifest_shape — get_manifest() lists layer, geodesic, property_cols per spatial dataset.
    test_profile_geom_or_latlon_required — Profiles without geometry source raise ValidationError.
    test_register_replaces_profile — Re-registering a profile silently replaces the old one.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from parrot.tools.dataset_manager.spatial.contracts import (
    DatasetSpatialProfile,
    SpatialFeatureCollection,
    SpatialFilterSpec,
)
from parrot.tools.dataset_manager.spatial.registry import (
    SPATIAL_PROFILE_REGISTRY,
    get_spatial_profile,
    register_spatial_profile,
    validate_profiles_exist,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_registry():
    """Clear SPATIAL_PROFILE_REGISTRY before and after each test."""
    SPATIAL_PROFILE_REGISTRY.clear()
    yield
    SPATIAL_PROFILE_REGISTRY.clear()


@pytest.fixture
def warehouse_point():
    """A sample warehouse coordinate (lat, lng)."""
    return (40.7128, -74.0060)


@pytest.fixture
def pg_school_profile():
    """A typical pg-backed school dataset profile."""
    return DatasetSpatialProfile(
        dataset="schools",
        geom_col="geog",
        layer="schools",
        property_cols=["name", "type"],
        description_template="{name} ({type})",
        geodesic=True,
    )


# ---------------------------------------------------------------------------
# SpatialFilterSpec tests
# ---------------------------------------------------------------------------


class TestSpatialFilterSpec:
    """Tests for the SpatialFilterSpec Pydantic model."""

    def test_spec_roundtrip(self, warehouse_point):
        """A well-formed spec round-trips correctly through Pydantic."""
        spec = SpatialFilterSpec(
            point=warehouse_point,
            radius=5,
            unit="mi",
            datasets=["schools"],
        )
        assert spec.point == warehouse_point
        assert spec.radius == 5.0
        assert spec.unit == "mi"
        assert spec.datasets == ["schools"]

    def test_spec_default_unit_is_mi(self, warehouse_point):
        """Default unit is 'mi' when not specified."""
        spec = SpatialFilterSpec(point=warehouse_point, radius=3.0, datasets=["hospitals"])
        assert spec.unit == "mi"

    def test_spec_accepts_km(self, warehouse_point):
        """Unit 'km' is accepted."""
        spec = SpatialFilterSpec(point=warehouse_point, radius=8.0, unit="km", datasets=["schools"])
        assert spec.unit == "km"

    def test_spec_accepts_m(self, warehouse_point):
        """Unit 'm' is accepted."""
        spec = SpatialFilterSpec(point=warehouse_point, radius=500.0, unit="m", datasets=["schools"])
        assert spec.unit == "m"

    def test_spec_rejects_malformed_point_single_element(self):
        """A point with a single element raises ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            SpatialFilterSpec(point=(40.7,), radius=5, datasets=["schools"])

    def test_spec_rejects_malformed_point_three_elements(self):
        """A point with three elements raises ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            SpatialFilterSpec(point=(40.7, -74.0, 0.0), radius=5, datasets=["schools"])

    def test_spec_rejects_non_positive_radius(self, warehouse_point):
        """A zero or negative radius raises ValidationError."""
        with pytest.raises ((ValidationError, ValueError)):
            SpatialFilterSpec(point=warehouse_point, radius=0.0, datasets=["schools"])
        with pytest.raises((ValidationError, ValueError)):
            SpatialFilterSpec(point=warehouse_point, radius=-1.0, datasets=["schools"])

    def test_spec_rejects_empty_datasets(self, warehouse_point):
        """An empty datasets list raises ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            SpatialFilterSpec(point=warehouse_point, radius=5.0, datasets=[])

    def test_spec_rejects_invalid_unit(self, warehouse_point):
        """An unknown unit literal raises ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            SpatialFilterSpec(point=warehouse_point, radius=5.0, unit="furlongs", datasets=["schools"])

    def test_spec_multiple_datasets(self, warehouse_point):
        """Multiple dataset names are stored and returned correctly."""
        spec = SpatialFilterSpec(
            point=warehouse_point,
            radius=5.0,
            datasets=["schools", "hospitals", "warehouses"],
        )
        assert len(spec.datasets) == 3

    def test_spec_rejects_latitude_out_of_bounds(self):
        """Latitude outside [-90, 90] raises ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            SpatialFilterSpec(point=(91.0, 0.0), radius=5, datasets=["schools"])
        with pytest.raises((ValidationError, ValueError)):
            SpatialFilterSpec(point=(-91.0, 0.0), radius=5, datasets=["schools"])

    def test_spec_rejects_longitude_out_of_bounds(self):
        """Longitude outside [-180, 180] raises ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            SpatialFilterSpec(point=(0.0, 181.0), radius=5, datasets=["schools"])
        with pytest.raises((ValidationError, ValueError)):
            SpatialFilterSpec(point=(0.0, -181.0), radius=5, datasets=["schools"])

    def test_spec_accepts_polar_coordinates(self):
        """Points at or near the poles (lat=±90) are valid."""
        spec_north = SpatialFilterSpec(point=(90.0, 0.0), radius=5, datasets=["schools"])
        assert spec_north.point == (90.0, 0.0)
        spec_south = SpatialFilterSpec(point=(-90.0, 0.0), radius=5, datasets=["schools"])
        assert spec_south.point == (-90.0, 0.0)

    def test_spec_accepts_date_line_longitude(self):
        """Longitude at exactly ±180 is valid."""
        spec = SpatialFilterSpec(point=(0.0, 180.0), radius=5, datasets=["schools"])
        assert spec.point == (0.0, 180.0)
        spec2 = SpatialFilterSpec(point=(0.0, -180.0), radius=5, datasets=["schools"])
        assert spec2.point == (0.0, -180.0)


# ---------------------------------------------------------------------------
# DatasetSpatialProfile tests
# ---------------------------------------------------------------------------


class TestDatasetSpatialProfile:
    """Tests for the DatasetSpatialProfile Pydantic model."""

    def test_profile_with_geom_col(self, pg_school_profile):
        """Profile with geom_col is valid."""
        assert pg_school_profile.geom_col == "geog"
        assert pg_school_profile.geodesic is True

    def test_profile_with_latlon(self):
        """Profile with lat_col + lng_col is valid."""
        p = DatasetSpatialProfile(
            dataset="hospitals",
            lat_col="latitude",
            lng_col="longitude",
            layer="hospitals",
            property_cols=["name", "address"],
            description_template="{name}",
            geodesic=False,
        )
        assert p.lat_col == "latitude"
        assert p.lng_col == "longitude"
        assert p.geodesic is False

    def test_profile_requires_geometry_source(self):
        """Profile without geom_col AND without lat/lng pair raises ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            DatasetSpatialProfile(
                dataset="schools",
                layer="schools",
                property_cols=["name"],
                description_template="{name}",
            )

    def test_profile_requires_both_lat_lng(self):
        """Providing only lat_col without lng_col raises ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            DatasetSpatialProfile(
                dataset="schools",
                lat_col="latitude",
                # lng_col missing
                layer="schools",
                property_cols=["name"],
                description_template="{name}",
            )

    def test_profile_requires_both_lat_lng_reverse(self):
        """Providing only lng_col without lat_col raises ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            DatasetSpatialProfile(
                dataset="schools",
                lng_col="longitude",
                # lat_col missing
                layer="schools",
                property_cols=["name"],
                description_template="{name}",
            )


# ---------------------------------------------------------------------------
# SpatialFeatureCollection tests
# ---------------------------------------------------------------------------


class TestSpatialFeatureCollection:
    """Tests for the SpatialFeatureCollection Pydantic model."""

    def test_empty_collection(self):
        """Default-constructed collection is valid and empty."""
        fc = SpatialFeatureCollection()
        assert fc.type == "FeatureCollection"
        assert fc.features == []
        assert fc.total_count == 0
        assert fc.capped is False
        assert fc.geodesic_paths == {}

    def test_collection_with_features(self):
        """A non-empty FeatureCollection carries the expected fields."""
        feature = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-74.006, 40.713]},
            "properties": {"name": "Test School", "source": "schools"},
        }
        fc = SpatialFeatureCollection(
            features=[feature],
            total_count=1,
            capped=False,
            geodesic_paths={"schools": True},
        )
        assert len(fc.features) == 1
        assert fc.total_count == 1
        assert fc.geodesic_paths["schools"] is True

    def test_capped_collection(self):
        """A capped collection carries total_count > len(features) and capped=True."""
        fc = SpatialFeatureCollection(
            features=[{"type": "Feature"} for _ in range(10)],
            total_count=500,
            capped=True,
            geodesic_paths={"schools": True},
        )
        assert fc.capped is True
        assert fc.total_count == 500
        assert len(fc.features) == 10
        assert fc.total_count > len(fc.features)


# ---------------------------------------------------------------------------
# Profile registry tests
# ---------------------------------------------------------------------------


class TestSpatialProfileRegistry:
    """Tests for SPATIAL_PROFILE_REGISTRY and helper functions."""

    def test_profile_registry_validates_dataset(self):
        """get_spatial_profile raises ValueError for an unregistered dataset."""
        with pytest.raises(ValueError, match="schools"):
            get_spatial_profile("schools")

    def test_register_and_get_profile(self, pg_school_profile):
        """Registering a profile allows it to be retrieved."""
        register_spatial_profile(pg_school_profile)
        retrieved = get_spatial_profile("schools")
        assert retrieved.dataset == "schools"
        assert retrieved.geom_col == "geog"
        assert retrieved.layer == "schools"

    def test_register_replaces_profile(self, pg_school_profile):
        """Re-registering a profile for the same dataset replaces the old one."""
        register_spatial_profile(pg_school_profile)
        new_profile = DatasetSpatialProfile(
            dataset="schools",
            geom_col="geometry",
            layer="schools_v2",
            property_cols=["name"],
            description_template="{name}",
        )
        register_spatial_profile(new_profile)
        retrieved = get_spatial_profile("schools")
        assert retrieved.layer == "schools_v2"
        assert retrieved.geom_col == "geometry"

    def test_validate_profiles_exist_passes(self, pg_school_profile):
        """validate_profiles_exist does not raise when all datasets have profiles."""
        register_spatial_profile(pg_school_profile)
        # Should not raise
        validate_profiles_exist(["schools"])

    def test_validate_profiles_exist_raises_on_missing(self, pg_school_profile):
        """validate_profiles_exist raises ValueError listing the missing dataset."""
        register_spatial_profile(pg_school_profile)
        with pytest.raises(ValueError, match="hospitals"):
            validate_profiles_exist(["schools", "hospitals"])

    def test_error_message_names_missing_dataset(self):
        """ValueError message includes the missing dataset name."""
        with pytest.raises(ValueError) as exc_info:
            get_spatial_profile("universities")
        assert "universities" in str(exc_info.value)

    def test_get_spatial_profile_lists_registered(self, pg_school_profile):
        """Error message for unknown dataset lists the registered datasets."""
        register_spatial_profile(pg_school_profile)
        with pytest.raises(ValueError) as exc_info:
            get_spatial_profile("hospitals")
        # The error should mention 'schools' as a registered option
        assert "schools" in str(exc_info.value)


# ---------------------------------------------------------------------------
# DatasetManager.get_manifest tests
# ---------------------------------------------------------------------------


class TestGetManifest:
    """Tests for DatasetManager.get_manifest()."""

    @pytest.fixture(autouse=True)
    def _sync_registry(self):
        """Ensure DatasetManager.get_manifest() sees the same registry object.

        The compiler test files load the spatial modules via importlib which can
        create a separate module instance in sys.modules.  When tool.py calls
        ``from .spatial.registry import SPATIAL_PROFILE_REGISTRY``, it gets the
        module that is currently registered under the canonical name
        ``parrot.tools.dataset_manager.spatial.registry``.  If that module instance
        is different from the one imported by this test file, registrations done
        here are invisible to get_manifest().

        Fix: replace the canonical sys.modules entry with this test file's module
        instance so all code paths share the same dict.
        """
        import sys
        canonical = "parrot.tools.dataset_manager.spatial.registry"
        # Build a reference to this file's own registry module instance
        import parrot.tools.dataset_manager.spatial.registry as _this_registry_mod
        original = sys.modules.get(canonical)
        sys.modules[canonical] = _this_registry_mod
        yield
        # Restore original module (if it was different)
        if original is not None:
            sys.modules[canonical] = original
        elif canonical in sys.modules:
            del sys.modules[canonical]

    def test_manifest_shape(self, pg_school_profile):
        """get_manifest() returns entries with layer, geodesic, property_cols."""
        from unittest.mock import MagicMock
        from parrot.tools.dataset_manager.tool import DatasetManager

        dm = DatasetManager()
        # Simulate a registered dataset
        mock_entry = MagicMock()
        dm._datasets["schools"] = mock_entry

        # Register a spatial profile
        register_spatial_profile(pg_school_profile)

        manifest = dm.get_manifest()

        assert len(manifest) == 1
        entry = manifest[0]
        assert entry["dataset"] == "schools"
        assert entry["layer"] == "schools"
        assert entry["geodesic"] is True
        assert entry["property_cols"] == ["name", "type"]

    def test_manifest_excludes_unregistered_datasets(self, pg_school_profile):
        """get_manifest() excludes profiles for datasets not in this manager."""
        from parrot.tools.dataset_manager.tool import DatasetManager

        dm = DatasetManager()
        # "schools" has a profile but is NOT added to dm._datasets
        register_spatial_profile(pg_school_profile)

        manifest = dm.get_manifest()
        # Should be empty — no matching datasets in this manager instance
        assert manifest == []

    def test_manifest_empty_when_no_profiles(self):
        """get_manifest() returns empty list when no spatial profiles are registered."""
        from parrot.tools.dataset_manager.tool import DatasetManager

        dm = DatasetManager()
        assert dm.get_manifest() == []

    def test_manifest_multiple_datasets(self):
        """get_manifest() lists all spatial datasets registered in this manager."""
        from unittest.mock import MagicMock
        from parrot.tools.dataset_manager.tool import DatasetManager

        dm = DatasetManager()

        # Register two spatial profiles and add both datasets
        for name in ("schools", "hospitals"):
            profile = DatasetSpatialProfile(
                dataset=name,
                lat_col="lat",
                lng_col="lng",
                layer=name,
                property_cols=["name"],
                description_template="{name}",
                geodesic=False,
            )
            register_spatial_profile(profile)
            dm._datasets[name] = MagicMock()

        manifest = dm.get_manifest()
        assert len(manifest) == 2
        layers = {e["layer"] for e in manifest}
        assert layers == {"schools", "hospitals"}
