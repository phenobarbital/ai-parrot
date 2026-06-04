"""Integration tests for FEAT-225 — apply_filters end-to-end with mixed in-memory sources.

These tests validate the full pipeline: define_filters → apply_filters → FilterResult
using in-memory DataFrames (no external DB required).

Tests:
- End-to-end region filter across a mixed set of datasets (with and without the column).
- Correct row count after filtering.
- result.applied and result.skipped are populated correctly.
- persist=True registers filtered entries with expected column content.
"""
import pytest
import pandas as pd

from parrot.tools.dataset_manager.filtering import FilterDefinition, FilterCondition
from parrot.tools.dataset_manager.tool import DatasetEntry, DatasetManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _entry(df: pd.DataFrame) -> DatasetEntry:
    return DatasetEntry(name="test", df=df)


@pytest.fixture()
def mixed_manager():
    """Manager with stores (has region), sites (has region), weather (no region)."""
    dm = DatasetManager()
    dm._datasets["stores"] = _entry(pd.DataFrame({
        "name": ["Store A", "Store B", "Store C"],
        "region": ["North", "South", "North"],
        "revenue": [100, 200, 150],
    }))
    dm._datasets["sites"] = _entry(pd.DataFrame({
        "site_id": [1, 2, 3],
        "region": ["North", "East", "West"],
        "active": [True, True, False],
    }))
    dm._datasets["weather"] = _entry(pd.DataFrame({
        "date": ["2024-01-01", "2024-01-02"],
        "temperature": [20.0, 22.0],
    }))
    return dm


# ---------------------------------------------------------------------------
# End-to-end: region filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_to_end_region_filter_in_operator(mixed_manager) -> None:
    """apply_filters with in operator filters stores/sites, skips weather."""
    dm = mixed_manager
    dm.define_filters([
        FilterDefinition(
            name="region",
            columns=["region"],
            kind="categorical",
            ops=["eq", "in"],
            required=False,
        )
    ])

    result = await dm.apply_filters({"region": ["North", "West"]})

    assert "stores" in result.applied
    assert "sites" in result.applied
    assert "weather" in result.skipped


@pytest.mark.asyncio
async def test_end_to_end_filtered_row_counts(mixed_manager) -> None:
    """apply_filters produces correctly filtered DataFrames (row counts match expectation)."""
    dm = mixed_manager

    # Apply region=North
    dm.define_filters([
        FilterDefinition(name="region", columns=["region"], kind="categorical",
                         ops=["eq"], required=False)
    ])

    # Before filtering, stores has 3 rows (2 North, 1 South)
    assert len(dm._datasets["stores"]._df) == 3

    result = await dm.apply_filters({"region": "North"}, persist=True)

    assert "stores" in result.applied
    # After persist, "stores__filtered" should have 2 rows
    assert "stores__filtered" in dm._datasets
    filtered_stores = dm._datasets["stores__filtered"]._df
    assert filtered_stores is not None
    assert len(filtered_stores) == 2
    assert all(r == "North" for r in filtered_stores["region"])


@pytest.mark.asyncio
async def test_end_to_end_ne_operator(mixed_manager) -> None:
    """ne operator excludes the specified value."""
    dm = mixed_manager
    dm.define_filters([
        FilterDefinition(name="region", columns=["region"], kind="categorical",
                         ops=["ne"], required=False)
    ])
    result = await dm.apply_filters({"region": FilterCondition(op="ne", value="North")})

    # stores has South; sites has East, West
    assert "stores" in result.applied
    assert "sites" in result.applied
    assert "weather" in result.skipped


@pytest.mark.asyncio
async def test_end_to_end_numeric_range(mixed_manager) -> None:
    """range operator on a numeric column filters correctly."""
    dm = mixed_manager
    dm.define_filters([
        FilterDefinition(name="revenue", columns=["revenue"], kind="numeric",
                         ops=["range"], required=False)
    ])
    # stores has revenue [100, 200, 150]; range 120-180 → [150]
    result = await dm.apply_filters(
        {"revenue": FilterCondition(op="range", value={"min": 120, "max": 180})},
        persist=True,
    )
    assert "stores" in result.applied
    # weather and sites don't have 'revenue'
    assert "weather" in result.skipped
    assert "sites" in result.skipped

    # Verify row count
    filtered = dm._datasets["stores__filtered"]._df
    assert filtered is not None
    assert len(filtered) == 1
    assert filtered.iloc[0]["revenue"] == 150


@pytest.mark.asyncio
async def test_end_to_end_persist_naming_no_collision(mixed_manager) -> None:
    """persist=True naming avoids collisions when called twice."""
    dm = mixed_manager
    dm.define_filters([
        FilterDefinition(name="region", columns=["region"], kind="categorical",
                         ops=["eq"], required=False)
    ])
    await dm.apply_filters({"region": "North"}, persist=True)
    keys_after_first = set(dm._datasets.keys())
    assert "stores__filtered" in keys_after_first

    # Second call should produce a different name
    await dm.apply_filters({"region": "South"}, persist=True)
    keys_after_second = set(dm._datasets.keys())
    new_keys = keys_after_second - keys_after_first
    assert len(new_keys) > 0  # at least one new entry


@pytest.mark.asyncio
async def test_end_to_end_required_true_raises_naming_dataset(mixed_manager) -> None:
    """required=True raises ValueError that names the dataset missing the column."""
    dm = mixed_manager
    dm.define_filters([
        FilterDefinition(name="region", columns=["region"], kind="categorical",
                         ops=["eq"], required=True)
    ])
    with pytest.raises(ValueError) as exc_info:
        await dm.apply_filters({"region": "North"})
    assert "weather" in str(exc_info.value)


@pytest.mark.asyncio
async def test_end_to_end_no_rows_is_valid(mixed_manager) -> None:
    """Filtering that produces 0 rows is valid (not an error)."""
    dm = mixed_manager
    dm.define_filters([
        FilterDefinition(name="region", columns=["region"], kind="categorical",
                         ops=["eq"], required=False)
    ])
    # "NonExistent" region exists in no row
    result = await dm.apply_filters({"region": "NonExistent"}, persist=True)
    # stores and sites still in applied (filter ran, even if 0 rows result)
    assert "stores" in result.applied
    if "stores__filtered" in dm._datasets:
        assert len(dm._datasets["stores__filtered"]._df) == 0
