"""Unit tests for FEAT-225 Module 4 — DatasetManager.apply_filters().

Tests cover:
- Recursive application: datasets with the column are filtered.
- Skip behavior: dataset without the column → result.skipped (required=False).
- required=True + missing column → ValueError naming the dataset.
- Bare scalar/list coercion in the request dict.
- FilterCondition request values.
- persist=True registers filtered datasets.
- Spatial delegation: kind=spatial → delegates to spatial_filter().
"""
import pytest
import pandas as pd

from parrot.tools.dataset_manager.filtering import FilterDefinition, FilterCondition
from parrot.tools.dataset_manager.spatial.contracts import DatasetSpatialProfile
from parrot.tools.dataset_manager.spatial.registry import (
    SPATIAL_PROFILE_REGISTRY,
    register_spatial_profile,
)
from parrot.tools.dataset_manager.tool import DatasetEntry, DatasetManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entry(df: pd.DataFrame) -> DatasetEntry:
    """Create a DatasetEntry from a DataFrame."""
    return DatasetEntry(name="test", df=df)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def clean_spatial_registry():
    SPATIAL_PROFILE_REGISTRY.clear()
    yield
    SPATIAL_PROFILE_REGISTRY.clear()


@pytest.fixture()
def manager_with_three_datasets():
    """Manager with: stores (region+lat+lng), sites (region+lat+lng), weather (lat+lng only)."""
    dm = DatasetManager()
    dm._datasets["stores"] = _entry(pd.DataFrame({
        "region": ["North", "South", "North"],
        "lat": [1.0, 2.0, 3.0],
        "lng": [1.0, 2.0, 3.0],
    }))
    dm._datasets["sites"] = _entry(pd.DataFrame({
        "region": ["North", "East"],
        "lat": [4.0, 5.0],
        "lng": [4.0, 5.0],
    }))
    dm._datasets["weather"] = _entry(pd.DataFrame({
        "lat": [6.0, 7.0],
        "lng": [6.0, 7.0],
        "temp": [20.0, 22.0],
    }))
    return dm


# ---------------------------------------------------------------------------
# Recursive application / skip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recursive_skip(manager_with_three_datasets) -> None:
    """Datasets with the column are filtered; datasets without are skipped."""
    dm = manager_with_three_datasets
    dm.define_filters([
        FilterDefinition(name="region", columns=["region"],
                         kind="categorical", ops=["in"], required=False)
    ])
    res = await dm.apply_filters({"region": ["North"]})
    assert "stores" in res.applied
    assert "sites" in res.applied
    assert "weather" in res.skipped


@pytest.mark.asyncio
async def test_all_applied(manager_with_three_datasets) -> None:
    """Filtering on a column present in all datasets applies to all."""
    dm = manager_with_three_datasets
    dm.define_filters([
        FilterDefinition(name="lat_filter", columns=["lat"],
                         kind="numeric", ops=["range"], required=False)
    ])
    res = await dm.apply_filters({"lat_filter": FilterCondition(op="range", value={"min": 1.0, "max": 10.0})})
    assert "stores" in res.applied
    assert "sites" in res.applied
    assert "weather" in res.applied
    assert not res.skipped


@pytest.mark.asyncio
async def test_scalar_coercion(manager_with_three_datasets) -> None:
    """Bare scalar in request → eq condition."""
    dm = manager_with_three_datasets
    dm.define_filters([
        FilterDefinition(name="region", columns=["region"],
                         kind="categorical", ops=["eq"], required=False)
    ])
    res = await dm.apply_filters({"region": "North"})
    assert "stores" in res.applied
    assert "sites" in res.applied


@pytest.mark.asyncio
async def test_list_coercion(manager_with_three_datasets) -> None:
    """Bare list in request → in condition."""
    dm = manager_with_three_datasets
    dm.define_filters([
        FilterDefinition(name="region", columns=["region"],
                         kind="categorical", ops=["in"], required=False)
    ])
    res = await dm.apply_filters({"region": ["North", "East"]})
    assert "stores" in res.applied


@pytest.mark.asyncio
async def test_filter_condition_in_request(manager_with_three_datasets) -> None:
    """FilterCondition instance in request dict is used directly."""
    dm = manager_with_three_datasets
    dm.define_filters([
        FilterDefinition(name="region", columns=["region"],
                         kind="categorical", ops=["ne"], required=False)
    ])
    res = await dm.apply_filters({"region": FilterCondition(op="ne", value="South")})
    assert "stores" in res.applied


# ---------------------------------------------------------------------------
# required=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_required_missing_raises(manager_with_three_datasets) -> None:
    """required=True + missing column raises ValueError naming the dataset."""
    dm = manager_with_three_datasets
    dm.define_filters([
        FilterDefinition(name="region", columns=["region"],
                         kind="categorical", ops=["eq"], required=True)
    ])
    with pytest.raises(ValueError, match="weather"):
        await dm.apply_filters({"region": "North"})


@pytest.mark.asyncio
async def test_required_false_skips_gracefully(manager_with_three_datasets) -> None:
    """required=False does NOT raise when column is missing."""
    dm = manager_with_three_datasets
    dm.define_filters([
        FilterDefinition(name="region", columns=["region"],
                         kind="categorical", ops=["eq"], required=False)
    ])
    res = await dm.apply_filters({"region": "North"})
    assert "weather" in res.skipped


# ---------------------------------------------------------------------------
# persist=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_registers_filtered_datasets(manager_with_three_datasets) -> None:
    """persist=True adds filtered datasets to the manager."""
    dm = manager_with_three_datasets
    dm.define_filters([
        FilterDefinition(name="region", columns=["region"],
                         kind="categorical", ops=["eq"], required=False)
    ])
    n_before = len(dm._datasets)
    res = await dm.apply_filters({"region": "North"}, persist=True)
    assert len(dm._datasets) > n_before
    # New entries should follow the naming policy
    new_keys = set(dm._datasets.keys()) - {"stores", "sites", "weather"}
    assert any("filtered" in k for k in new_keys)


@pytest.mark.asyncio
async def test_no_persist_does_not_mutate_manager(manager_with_three_datasets) -> None:
    """Default persist=False does not modify self._datasets."""
    dm = manager_with_three_datasets
    dm.define_filters([
        FilterDefinition(name="region", columns=["region"],
                         kind="categorical", ops=["eq"], required=False)
    ])
    keys_before = set(dm._datasets.keys())
    await dm.apply_filters({"region": "North"})
    assert set(dm._datasets.keys()) == keys_before


# ---------------------------------------------------------------------------
# Unknown filter key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_filter_key_raises(manager_with_three_datasets) -> None:
    """Requesting a filter not in _filter_defs raises KeyError."""
    dm = manager_with_three_datasets
    with pytest.raises(KeyError, match="ghost_filter"):
        await dm.apply_filters({"ghost_filter": "value"})


# ---------------------------------------------------------------------------
# Spatial delegation (mock spatial_filter)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spatial_delegates_to_spatial_filter(
    manager_with_three_datasets, clean_spatial_registry, monkeypatch
) -> None:
    """kind=spatial request is routed to spatial_filter()."""
    dm = manager_with_three_datasets

    # Register spatial profiles for stores and sites
    register_spatial_profile(DatasetSpatialProfile(
        dataset="stores", lat_col="lat", lng_col="lng", layer="stores", property_cols=[]
    ))
    register_spatial_profile(DatasetSpatialProfile(
        dataset="sites", lat_col="lat", lng_col="lng", layer="sites", property_cols=[]
    ))

    # Define a spatial filter
    dm.define_filters([
        FilterDefinition(name="geo", columns=["lat", "lng"], kind="spatial", ops=["radius"])
    ])

    # Mock spatial_filter to avoid real DB calls
    from parrot.tools.dataset_manager.spatial.contracts import SpatialResult
    mock_result = SpatialResult(version=2, layers={})
    spatial_filter_calls = []

    async def _mock_spatial_filter(spec, cap_per_dataset=1000):
        spatial_filter_calls.append(spec)
        return mock_result

    monkeypatch.setattr(dm, "spatial_filter", _mock_spatial_filter)

    res = await dm.apply_filters({
        "geo": {"point": (1.0, 2.0), "radius": 5.0, "unit": "mi"}
    })

    assert len(spatial_filter_calls) == 1
    assert "stores" in res.applied
    assert "sites" in res.applied
