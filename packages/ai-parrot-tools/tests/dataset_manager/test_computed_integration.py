"""
Unit tests for DatasetEntry computed column integration (TASK-428).

Tests cover:
- computed_columns parameter in __init__
- Immediate application when df is provided
- Application in materialize() post-fetch, pre-categorization
- columns property includes computed names in prefetch state
- _column_metadata injects computed descriptions
- Failure resilience (one failing column doesn't abort others)
- Column ordering (A before B if B depends on A)
"""
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock

from parrot.tools.dataset_manager.tool import DatasetEntry
from parrot.tools.dataset_manager.computed import (
    ComputedColumnDef,
    COMPUTED_FUNCTIONS,
)


@pytest.fixture(autouse=True)
def ensure_builtins():
    """Ensure built-in functions are loaded."""
    from parrot.tools.dataset_manager.computed import _ensure_builtins
    _ensure_builtins()
    yield


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        "revenue": [100.0, 200.0],
        "expenses": [60.0, 80.0],
        "first": ["John", "Jane"],
        "last": ["Doe", "Smith"],
    })


@pytest.fixture
def computed_cols():
    return [
        ComputedColumnDef(
            name="ebitda",
            func="math_operation",
            columns=["revenue", "expenses"],
            kwargs={"operation": "subtract"},
            description="Earnings metric",
        ),
        ComputedColumnDef(
            name="full_name",
            func="concatenate",
            columns=["first", "last"],
            kwargs={"sep": " "},
            description="Display name",
        ),
    ]


class TestDatasetEntryComputed:
    def test_init_with_df_applies_computed(self, sample_df, computed_cols):
        """Computed columns applied immediately when df provided."""
        entry = DatasetEntry(
            name="test", df=sample_df, computed_columns=computed_cols
        )
        assert "ebitda" in entry._df.columns
        assert "full_name" in entry._df.columns

    def test_ebitda_values_correct(self, sample_df, computed_cols):
        """EBITDA = revenue - expenses."""
        entry = DatasetEntry(
            name="test", df=sample_df, computed_columns=computed_cols
        )
        assert list(entry._df["ebitda"]) == [40.0, 120.0]

    def test_init_without_computed_unchanged(self, sample_df):
        """Existing behavior preserved when no computed columns."""
        entry = DatasetEntry(name="test", df=sample_df)
        assert entry._computed_columns == []

    def test_computed_columns_stored(self, sample_df, computed_cols):
        """_computed_columns attribute stored correctly."""
        entry = DatasetEntry(
            name="test", df=sample_df, computed_columns=computed_cols
        )
        assert len(entry._computed_columns) == 2

    @pytest.mark.asyncio
    async def test_materialize_applies_computed(self, computed_cols):
        """Computed columns applied after materialize fetch."""
        source = MagicMock()
        source.fetch = AsyncMock(return_value=pd.DataFrame({
            "revenue": [100.0], "expenses": [60.0],
            "first": ["John"], "last": ["Doe"],
        }))
        source.has_builtin_cache = False
        entry = DatasetEntry(
            name="test", source=source, computed_columns=computed_cols,
        )
        df = await entry.materialize()
        assert "ebitda" in df.columns
        assert df["ebitda"].iloc[0] == 40.0

    @pytest.mark.asyncio
    async def test_materialize_applies_before_categorize(self, computed_cols):
        """Computed columns included in _column_types after materialize."""
        source = MagicMock()
        source.fetch = AsyncMock(return_value=pd.DataFrame({
            "revenue": [100.0], "expenses": [60.0],
            "first": ["John"], "last": ["Doe"],
        }))
        source.has_builtin_cache = False
        entry = DatasetEntry(
            name="test", source=source, computed_columns=computed_cols,
            auto_detect_types=True,
        )
        df = await entry.materialize()
        assert entry._column_types is not None
        assert "ebitda" in entry._column_types

    def test_columns_includes_computed_prefetch(self, computed_cols):
        """columns property includes computed names even before load."""
        source = MagicMock()
        source._schema = {"revenue": "float", "expenses": "float"}
        entry = DatasetEntry(
            name="test", source=source, computed_columns=computed_cols,
        )
        cols = entry.columns
        assert "ebitda" in cols
        assert "full_name" in cols

    def test_columns_property_loaded_no_duplicates(self, sample_df, computed_cols):
        """When loaded, columns comes from _df (no duplication)."""
        entry = DatasetEntry(
            name="test", df=sample_df, computed_columns=computed_cols
        )
        cols = entry.columns
        assert cols.count("ebitda") == 1
        assert cols.count("full_name") == 1

    def test_column_metadata_computed_description(self, sample_df, computed_cols):
        """_column_metadata injects computed column descriptions."""
        entry = DatasetEntry(
            name="test", df=sample_df, computed_columns=computed_cols
        )
        meta = entry._column_metadata
        assert "ebitda" in meta
        assert meta["ebitda"]["description"] == "Earnings metric"
        assert meta["full_name"]["description"] == "Display name"

    def test_failure_resilience(self, sample_df):
        """One failing computed column doesn't abort others."""
        cols = [
            ComputedColumnDef(
                name="bad", func="nonexistent_func", columns=["revenue"],
            ),
            ComputedColumnDef(
                name="ebitda", func="math_operation",
                columns=["revenue", "expenses"],
                kwargs={"operation": "subtract"},
            ),
        ]
        entry = DatasetEntry(name="test", df=sample_df, computed_columns=cols)
        assert "ebitda" in entry._df.columns
        assert "bad" not in entry._df.columns

    def test_column_ordering(self):
        """Computed column B can depend on computed column A if A is listed first."""
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        cols = [
            ComputedColumnDef(
                name="c", func="math_operation",
                columns=["a", "b"], kwargs={"operation": "add"},
            ),
            ComputedColumnDef(
                name="d", func="math_operation",
                columns=["c", "a"], kwargs={"operation": "subtract"},
            ),
        ]
        entry = DatasetEntry(name="test", df=df, computed_columns=cols)
        assert list(entry._df["c"]) == [4, 6]
        assert list(entry._df["d"]) == [3, 4]  # c - a

    def test_no_computed_no_extra_columns(self, sample_df):
        """Without computed columns, no extra columns are added."""
        entry = DatasetEntry(name="test", df=sample_df)
        expected_cols = set(sample_df.columns)
        assert set(entry._df.columns) == expected_cols

    def test_computed_columns_none_treated_as_empty(self, sample_df):
        """computed_columns=None results in empty _computed_columns list."""
        entry = DatasetEntry(name="test", df=sample_df, computed_columns=None)
        assert entry._computed_columns == []
