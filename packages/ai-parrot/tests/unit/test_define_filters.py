"""Unit tests for FEAT-225 Module 2 — DatasetManager._filter_defs + define_filters().

Tests cover:
- _filter_defs initialized independently on each instance.
- define_filters() stores definitions on the instance.
- Duplicate name replacement is allowed.
- spatial kind without a registered profile raises ValueError.
- Two managers do not share filter definitions.
"""
import pytest

from parrot.tools.dataset_manager.filtering import FilterDefinition
from parrot.tools.dataset_manager.spatial.contracts import DatasetSpatialProfile
from parrot.tools.dataset_manager.spatial.registry import (
    SPATIAL_PROFILE_REGISTRY,
    register_spatial_profile,
)
from parrot.tools.dataset_manager.tool import DatasetManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def clean_spatial_registry():
    """Ensure the spatial profile registry is clean before and after each test."""
    SPATIAL_PROFILE_REGISTRY.clear()
    yield
    SPATIAL_PROFILE_REGISTRY.clear()


@pytest.fixture()
def empty_manager():
    """A DatasetManager with no datasets."""
    return DatasetManager()


@pytest.fixture()
def manager_with_region_col(empty_manager):
    """A DatasetManager with one in-memory dataset that has a 'region' column."""
    import pandas as pd

    df = pd.DataFrame({"region": ["North", "South"], "value": [1, 2]})
    empty_manager._datasets["stores"] = _make_dataset_entry(df)
    return empty_manager


@pytest.fixture()
def manager_with_spatial_dataset(empty_manager, clean_spatial_registry):
    """A DatasetManager with a spatial-profiled dataset."""
    import pandas as pd

    df = pd.DataFrame({"lat": [1.0], "lng": [2.0]})
    empty_manager._datasets["geo_ds"] = _make_dataset_entry(df)
    register_spatial_profile(
        DatasetSpatialProfile(
            dataset="geo_ds",
            lat_col="lat",
            lng_col="lng",
            layer="geo_ds",
            property_cols=[],
        )
    )
    return empty_manager


@pytest.fixture()
def manager_without_spatial_profile(empty_manager, clean_spatial_registry):
    """A DatasetManager with a dataset but NO spatial profile registered."""
    import pandas as pd

    df = pd.DataFrame({"lat": [1.0], "lng": [2.0]})
    empty_manager._datasets["plain_ds"] = _make_dataset_entry(df)
    # No spatial profile registered
    return empty_manager


def _make_dataset_entry(df):
    """Create a DatasetEntry from a DataFrame (uses the proper constructor)."""
    from parrot.tools.dataset_manager.tool import DatasetEntry

    return DatasetEntry(name="test", df=df)


# ---------------------------------------------------------------------------
# _filter_defs initialization
# ---------------------------------------------------------------------------


def test_filter_defs_initialized_empty(empty_manager) -> None:
    """Each new DatasetManager starts with an empty _filter_defs dict."""
    assert hasattr(empty_manager, "_filter_defs")
    assert empty_manager._filter_defs == {}


def test_two_managers_have_independent_filter_defs() -> None:
    """Two DatasetManager instances do not share _filter_defs."""
    m1 = DatasetManager()
    m2 = DatasetManager()
    assert m1._filter_defs is not m2._filter_defs


# ---------------------------------------------------------------------------
# define_filters — stores on instance
# ---------------------------------------------------------------------------


def test_define_filters_stores_on_instance(manager_with_region_col) -> None:
    """define_filters stores the definition keyed by name."""
    dm = manager_with_region_col
    dm.define_filters([
        FilterDefinition(name="region", columns=["region"],
                         kind="categorical", ops=["eq", "in"])
    ])
    assert "region" in dm._filter_defs
    assert dm._filter_defs["region"].kind == "categorical"


def test_define_filters_multiple_definitions(manager_with_region_col) -> None:
    """Multiple definitions can be stored at once."""
    import pandas as pd

    # Add a second dataset with a numeric column
    df2 = pd.DataFrame({"price": [10.0, 20.0]})
    manager_with_region_col._datasets["prices"] = _make_dataset_entry(df2)

    manager_with_region_col.define_filters([
        FilterDefinition(name="region", columns=["region"],
                         kind="categorical", ops=["eq"]),
        FilterDefinition(name="price", columns=["price"],
                         kind="numeric", ops=["range"]),
    ])
    assert "region" in manager_with_region_col._filter_defs
    assert "price" in manager_with_region_col._filter_defs


def test_define_filters_replaces_duplicate_name(manager_with_region_col) -> None:
    """Defining the same filter name twice replaces the previous definition."""
    dm = manager_with_region_col
    dm.define_filters([
        FilterDefinition(name="region", columns=["region"],
                         kind="categorical", ops=["eq"])
    ])
    assert dm._filter_defs["region"].ops == ["eq"]

    dm.define_filters([
        FilterDefinition(name="region", columns=["region"],
                         kind="categorical", ops=["eq", "ne", "in"])
    ])
    assert dm._filter_defs["region"].ops == ["eq", "ne", "in"]


# ---------------------------------------------------------------------------
# Two managers do not share definitions
# ---------------------------------------------------------------------------


def test_two_managers_do_not_share_defs() -> None:
    """Definitions on one manager do not appear on another."""
    m1 = DatasetManager()
    m2 = DatasetManager()

    import pandas as pd
    df = pd.DataFrame({"region": ["North"]})
    m1._datasets["stores"] = _make_dataset_entry(df)

    m1.define_filters([
        FilterDefinition(name="region", columns=["region"],
                         kind="categorical", ops=["eq"])
    ])
    assert "region" in m1._filter_defs
    assert "region" not in m2._filter_defs


# ---------------------------------------------------------------------------
# Spatial kind validation
# ---------------------------------------------------------------------------


def test_define_filters_spatial_requires_profile(
    manager_without_spatial_profile,
) -> None:
    """kind='spatial' without a registered profile raises ValueError."""
    with pytest.raises(ValueError, match="spatial"):
        manager_without_spatial_profile.define_filters([
            FilterDefinition(name="geo", columns=["lat", "lng"],
                             kind="spatial", ops=["radius"])
        ])


def test_define_filters_spatial_ok_with_profile(
    manager_with_spatial_dataset,
) -> None:
    """kind='spatial' with a registered profile is stored successfully."""
    dm = manager_with_spatial_dataset
    dm.define_filters([
        FilterDefinition(name="geo", columns=["lat", "lng"],
                         kind="spatial", ops=["radius"])
    ])
    assert "geo" in dm._filter_defs
    assert dm._filter_defs["geo"].kind == "spatial"


# ---------------------------------------------------------------------------
# No column coverage warning (non-fatal)
# ---------------------------------------------------------------------------


def test_define_filters_no_column_coverage_does_not_raise(empty_manager) -> None:
    """define_filters logs a warning but does not raise when no dataset has the column."""
    # empty_manager has no datasets at all; should warn but not fail
    empty_manager.define_filters([
        FilterDefinition(name="unknown_col", columns=["ghost_column"],
                         kind="categorical", ops=["eq"])
    ])
    assert "unknown_col" in empty_manager._filter_defs
