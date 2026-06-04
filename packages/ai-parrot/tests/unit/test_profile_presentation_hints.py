"""Tests for FEAT-221 TASK-1447: Presentation hints on DatasetSpatialProfile.

Verifies all new optional fields are backward-compatible and validated correctly.
"""
from __future__ import annotations

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Backward-compatibility: existing profiles still construct without new fields
# ─────────────────────────────────────────────────────────────────────────────


def test_optional_presentation_fields_default():
    """New fields default to None/empty/geojson — existing profiles unaffected."""
    from parrot.tools.dataset_manager.spatial.contracts import DatasetSpatialProfile

    p = DatasetSpatialProfile(
        dataset="schools",
        lat_col="lat",
        lng_col="lng",
        layer="schools",
    )
    assert p.label_col is None
    assert p.tooltip_template is None
    assert p.column_titles == {}
    assert p.column_formats == {}
    assert p.default_data_shape == "geojson"


def test_existing_profile_fields_unchanged():
    """Core FEAT-219 fields (property_cols, description_template, geodesic) work as before."""
    from parrot.tools.dataset_manager.spatial.contracts import DatasetSpatialProfile

    p = DatasetSpatialProfile(
        dataset="malls",
        lat_col="latitude",
        lng_col="longitude",
        layer="malls",
        property_cols=["name", "type"],
        description_template="{name} ({type})",
        geodesic=False,
    )
    assert p.property_cols == ["name", "type"]
    assert p.description_template == "{name} ({type})"
    assert p.geodesic is False


def test_geometry_source_validator_still_works():
    """The existing _validate_geometry_source validator still raises on missing geometry."""
    from parrot.tools.dataset_manager.spatial.contracts import DatasetSpatialProfile

    with pytest.raises((ValueError, Exception)):
        DatasetSpatialProfile(
            dataset="no_geom",
            layer="no_geom",
            # neither lat/lng nor geom_col provided
        )


# ─────────────────────────────────────────────────────────────────────────────
# New presentation hint fields
# ─────────────────────────────────────────────────────────────────────────────


def test_presentation_fields_set():
    """All new presentation hint fields accept correct values."""
    from parrot.tools.dataset_manager.spatial.contracts import DatasetSpatialProfile

    p = DatasetSpatialProfile(
        dataset="schools",
        lat_col="lat",
        lng_col="lng",
        layer="schools",
        property_cols=["name", "enrollment"],
        label_col="name",
        tooltip_template="{name} ({enrollment})",
        column_titles={"enrollment": "Students"},
        column_formats={"enrollment": "id"},
        default_data_shape="rows",
    )
    assert p.label_col == "name"
    assert p.tooltip_template == "{name} ({enrollment})"
    assert p.column_titles["enrollment"] == "Students"
    assert p.column_formats["enrollment"] == "id"
    assert p.default_data_shape == "rows"


def test_label_col_set():
    """label_col stores the property key for the marker label."""
    from parrot.tools.dataset_manager.spatial.contracts import DatasetSpatialProfile

    p = DatasetSpatialProfile(
        dataset="schools",
        lat_col="lat",
        lng_col="lng",
        layer="schools",
        label_col="school_name",
    )
    assert p.label_col == "school_name"


def test_tooltip_template_distinct_from_description_template():
    """tooltip_template and description_template are independent fields."""
    from parrot.tools.dataset_manager.spatial.contracts import DatasetSpatialProfile

    p = DatasetSpatialProfile(
        dataset="schools",
        lat_col="lat",
        lng_col="lng",
        layer="schools",
        description_template="{name}",
        tooltip_template="{name} — {type}",
    )
    assert p.description_template == "{name}"
    assert p.tooltip_template == "{name} — {type}"


def test_column_titles_dict():
    """column_titles is a dict mapping property name → human title."""
    from parrot.tools.dataset_manager.spatial.contracts import DatasetSpatialProfile

    p = DatasetSpatialProfile(
        dataset="schools",
        lat_col="lat",
        lng_col="lng",
        layer="schools",
        property_cols=["name", "enrollment", "type"],
        column_titles={"name": "School Name", "enrollment": "Students", "type": "Level"},
    )
    assert p.column_titles["name"] == "School Name"
    assert p.column_titles["enrollment"] == "Students"


def test_column_formats_dict():
    """column_formats is a dict mapping property name → format hint."""
    from parrot.tools.dataset_manager.spatial.contracts import DatasetSpatialProfile

    p = DatasetSpatialProfile(
        dataset="schools",
        lat_col="lat",
        lng_col="lng",
        layer="schools",
        property_cols=["enrollment"],
        column_formats={"enrollment": "id"},
    )
    assert p.column_formats["enrollment"] == "id"


def test_default_data_shape_geojson():
    """default_data_shape defaults to 'geojson'."""
    from parrot.tools.dataset_manager.spatial.contracts import DatasetSpatialProfile

    p = DatasetSpatialProfile(
        dataset="schools",
        lat_col="lat",
        lng_col="lng",
        layer="schools",
    )
    assert p.default_data_shape == "geojson"


def test_default_data_shape_rows():
    """default_data_shape can be set to 'rows'."""
    from parrot.tools.dataset_manager.spatial.contracts import DatasetSpatialProfile

    p = DatasetSpatialProfile(
        dataset="schools",
        lat_col="lat",
        lng_col="lng",
        layer="schools",
        default_data_shape="rows",
    )
    assert p.default_data_shape == "rows"


def test_tooltip_fallback_to_description_template():
    """When tooltip_template is None, the caller should fall back to description_template."""
    from parrot.tools.dataset_manager.spatial.contracts import DatasetSpatialProfile

    p = DatasetSpatialProfile(
        dataset="schools",
        lat_col="lat",
        lng_col="lng",
        layer="schools",
        description_template="{name}",
        # tooltip_template NOT set
    )
    # renderer should use description_template as fallback
    effective_tooltip = p.tooltip_template or p.description_template
    assert effective_tooltip == "{name}"


def test_geom_col_profile_with_hints():
    """Profile with geom_col geometry source also accepts presentation hints."""
    from parrot.tools.dataset_manager.spatial.contracts import DatasetSpatialProfile

    p = DatasetSpatialProfile(
        dataset="parks",
        geom_col="geog",
        layer="parks",
        label_col="park_name",
        tooltip_template="{park_name}",
        column_titles={"park_name": "Park Name"},
        default_data_shape="rows",
    )
    assert p.label_col == "park_name"
    assert p.default_data_shape == "rows"
