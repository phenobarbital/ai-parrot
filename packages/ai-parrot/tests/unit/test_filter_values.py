"""Unit tests for FEAT-225 Module 5 — get_filter_values() + filtering/values.py.

Tests cover:
- Inferred distinct values from in-memory datasets.
- Sorted and de-duplicated results.
- Cardinality cap truncates and logs.
- values_source column+dataset restricts inference.
- Cache hit on second call.
- Unknown filter name raises KeyError.
- values.py helper functions in isolation.
"""
import pytest
import pandas as pd

from parrot.tools.dataset_manager.filtering import FilterDefinition, ValuesSource
from parrot.tools.dataset_manager.filtering.values import (
    DEFAULT_CARDINALITY_CAP,
    apply_cardinality_cap,
    infer_values_from_datasets,
)
from parrot.tools.dataset_manager.tool import DatasetEntry, DatasetManager


# ---------------------------------------------------------------------------
# Helpers + Fixtures
# ---------------------------------------------------------------------------


def _entry(df: pd.DataFrame) -> DatasetEntry:
    return DatasetEntry(name="test", df=df)


@pytest.fixture()
def manager_with_regions():
    """Manager: stores (region North/South/North), sites (region North/East)."""
    dm = DatasetManager()
    dm._datasets["stores"] = _entry(pd.DataFrame({
        "region": ["North", "South", "North"],
        "value": [1, 2, 3],
    }))
    dm._datasets["sites"] = _entry(pd.DataFrame({
        "region": ["North", "East"],
        "value": [4, 5],
    }))
    return dm


@pytest.fixture()
def manager_with_three_datasets():
    """Manager: stores+sites have region; weather does not."""
    dm = DatasetManager()
    dm._datasets["stores"] = _entry(pd.DataFrame({
        "region": ["North", "South"],
    }))
    dm._datasets["sites"] = _entry(pd.DataFrame({
        "region": ["North", "West"],
    }))
    dm._datasets["weather"] = _entry(pd.DataFrame({
        "temp": [20.0, 22.0],
    }))
    return dm


# ---------------------------------------------------------------------------
# infer_values_from_datasets (helper isolation tests)
# ---------------------------------------------------------------------------


def test_infer_values_basic(manager_with_regions) -> None:
    """infer_values_from_datasets returns sorted distinct values."""
    vals = infer_values_from_datasets("region", manager_with_regions._datasets)
    assert sorted(vals) == vals
    assert "North" in vals
    assert "South" in vals
    assert "East" in vals
    assert vals.count("North") == 1  # deduplicated


def test_infer_values_restrict_to_dataset(manager_with_regions) -> None:
    """restrict_to_dataset limits inference to one dataset."""
    vals = infer_values_from_datasets(
        "region", manager_with_regions._datasets, restrict_to_dataset="stores"
    )
    assert "East" not in vals   # East is only in sites
    assert "South" in vals


def test_infer_values_missing_column(manager_with_three_datasets) -> None:
    """Datasets without the column are skipped."""
    vals = infer_values_from_datasets("region", manager_with_three_datasets._datasets)
    # weather has no region column
    assert "North" in vals


def test_infer_values_no_loaded_df() -> None:
    """Entries with _df=None are skipped (not yet materialized)."""
    dm = DatasetManager()
    # Add an entry without a df (simulates unloaded source)
    entry = DatasetEntry(name="ghost", df=pd.DataFrame({"region": ["X"]}))
    entry._df = None  # override to simulate unloaded
    dm._datasets["ghost"] = entry
    vals = infer_values_from_datasets("region", dm._datasets)
    assert vals == []


# ---------------------------------------------------------------------------
# apply_cardinality_cap (helper isolation tests)
# ---------------------------------------------------------------------------


def test_cardinality_cap_no_truncation() -> None:
    """Lists within the cap are returned as-is."""
    values = list(range(10))
    result = apply_cardinality_cap(values, cap=100)
    assert result == values


def test_cardinality_cap_truncates(caplog) -> None:
    """Lists exceeding the cap are truncated and a warning is logged."""
    import logging
    values = list(range(200))
    with caplog.at_level(logging.WARNING):
        result = apply_cardinality_cap(values, cap=50, filter_name="myfilter")
    assert len(result) == 50
    assert "myfilter" in caplog.text
    assert "200" in caplog.text


def test_cardinality_cap_default() -> None:
    """Default cap constant is accessible and positive."""
    assert DEFAULT_CARDINALITY_CAP > 0


# ---------------------------------------------------------------------------
# DatasetManager.get_filter_values (full method tests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inferred_union_distinct(manager_with_three_datasets) -> None:
    """Inference unions DISTINCT across datasets with the column; sorted + deduped."""
    dm = manager_with_three_datasets
    dm.define_filters([
        FilterDefinition(name="region", columns=["region"],
                         kind="categorical", ops=["in"])
    ])
    vals = await dm.get_filter_values("region")
    assert sorted(vals) == vals
    assert len(vals) == len(set(vals))  # deduped
    assert "North" in vals
    assert "West" in vals


@pytest.mark.asyncio
async def test_unknown_filter_raises(manager_with_regions) -> None:
    """get_filter_values raises KeyError for unknown filter name."""
    with pytest.raises(KeyError, match="ghost"):
        await manager_with_regions.get_filter_values("ghost")


@pytest.mark.asyncio
async def test_values_source_column_restricts(manager_with_regions) -> None:
    """values_source with dataset restricts inference to that dataset."""
    dm = manager_with_regions
    dm.define_filters([
        FilterDefinition(
            name="region",
            columns=["region"],
            kind="categorical",
            ops=["in"],
            values_source=ValuesSource(column="region", dataset="stores"),
        )
    ])
    vals = await dm.get_filter_values("region")
    # stores has North, South; sites has North, East
    assert "South" in vals
    assert "East" not in vals  # restricted to stores


@pytest.mark.asyncio
async def test_cache_hit_second_call(manager_with_regions) -> None:
    """Second call to get_filter_values uses the cache (same result)."""
    dm = manager_with_regions
    dm.define_filters([
        FilterDefinition(name="region", columns=["region"],
                         kind="categorical", ops=["in"])
    ])
    vals1 = await dm.get_filter_values("region")
    # Mutate the underlying dataset — cache should return stale (first) result
    dm._datasets["stores"]._df = pd.DataFrame({"region": ["Outer"], "value": [99]})
    vals2 = await dm.get_filter_values("region")
    assert vals1 == vals2  # cache hit; stale values


@pytest.mark.asyncio
async def test_cardinality_cap_applied(caplog) -> None:
    """Cardinality cap truncates large value lists."""
    import logging
    dm = DatasetManager()
    # 200 unique regions
    dm._datasets["big"] = _entry(pd.DataFrame({"region": [f"R{i}" for i in range(200)]}))
    dm.define_filters([
        FilterDefinition(name="region", columns=["region"], kind="categorical", ops=["in"])
    ])
    with caplog.at_level(logging.WARNING):
        vals = await dm.get_filter_values("region", cardinality_cap=50)
    assert len(vals) == 50
    assert "region" in caplog.text
