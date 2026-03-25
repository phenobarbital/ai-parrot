"""
Unit tests for DatasetManager add_* methods computed_columns parameter (TASK-429).

Tests cover:
- add_dataframe with computed_columns
- add_dataframe without computed_columns (backward compat)
- add_query with computed_columns
- add_sql_source with computed_columns
- Verify parameter flows through to DatasetEntry
"""
import pytest
import pandas as pd
from parrot.tools.dataset_manager.tool import DatasetManager
from parrot.tools.dataset_manager.computed import ComputedColumnDef


@pytest.fixture
def dm():
    return DatasetManager(generate_guide=False)


@pytest.fixture
def computed_cols():
    return [
        ComputedColumnDef(
            name="total",
            func="math_operation",
            columns=["a", "b"],
            kwargs={"operation": "add"},
        ),
    ]


class TestAddMethodsComputedColumns:
    def test_add_dataframe_with_computed(self, dm, computed_cols):
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        dm.add_dataframe("test", df, computed_columns=computed_cols)
        entry = dm._datasets["test"]
        assert len(entry._computed_columns) == 1
        assert "total" in entry._df.columns
        assert list(entry._df["total"]) == [4, 6]

    def test_add_dataframe_without_computed(self, dm):
        """Backward compatibility: no computed_columns param."""
        df = pd.DataFrame({"a": [1]})
        dm.add_dataframe("test", df)
        entry = dm._datasets["test"]
        assert entry._computed_columns == []

    def test_add_dataframe_computed_none(self, dm):
        """computed_columns=None is treated as no computed columns."""
        df = pd.DataFrame({"a": [1]})
        dm.add_dataframe("test", df, computed_columns=None)
        entry = dm._datasets["test"]
        assert entry._computed_columns == []

    def test_add_query_with_computed(self, dm, computed_cols):
        dm.add_query("test", "some_slug", computed_columns=computed_cols)
        entry = dm._datasets["test"]
        assert len(entry._computed_columns) == 1

    def test_add_query_without_computed(self, dm):
        dm.add_query("test", "some_slug")
        entry = dm._datasets["test"]
        assert entry._computed_columns == []

    def test_add_sql_source_with_computed(self, dm, computed_cols):
        dm.add_sql_source(
            "test", sql="SELECT 1", driver="postgresql",
            computed_columns=computed_cols,
        )
        entry = dm._datasets["test"]
        assert len(entry._computed_columns) == 1

    def test_add_sql_source_without_computed(self, dm):
        dm.add_sql_source("test", sql="SELECT 1", driver="postgresql")
        entry = dm._datasets["test"]
        assert entry._computed_columns == []

    def test_add_dataframe_columns_includes_computed(self, dm, computed_cols):
        """After add_dataframe with computed, computed column names appear in entry.columns."""
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        dm.add_dataframe("test", df, computed_columns=computed_cols)
        entry = dm._datasets["test"]
        assert "total" in entry.columns

    def test_add_dataframe_returns_confirmation(self, dm, computed_cols):
        """Return message includes dataset name."""
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        result = dm.add_dataframe("test", df, computed_columns=computed_cols)
        assert "test" in result
