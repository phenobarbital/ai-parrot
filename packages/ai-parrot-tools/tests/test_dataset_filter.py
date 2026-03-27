"""Tests for DatasetManager._apply_filter and add_dataset(filter=...).

Covers:
- _apply_filter: scalar, list, tuple, set, multiple keys, empty result,
  missing column, None/empty filter.
- add_dataset integration: dataframe with filter, backward compat without filter.
"""
import pandas as pd
import pytest

from parrot.tools.dataset_manager import DatasetManager


# ─────────────────────────────────────────────────────────────────────────────
# Sample data
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame({
        "project": ["Pokemon", "Pokemon", "Digimon", "Digimon", "YuGiOh"],
        "status": ["active", "pending", "active", "archived", "active"],
        "score": [10, 20, 30, 40, 50],
    })


@pytest.fixture
def dm() -> DatasetManager:
    return DatasetManager()


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests for _apply_filter
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyFilter:

    def test_scalar_value(self, sample_df: pd.DataFrame):
        result = DatasetManager._apply_filter(sample_df, {"project": "Pokemon"})
        assert len(result) == 2
        assert list(result["project"].unique()) == ["Pokemon"]

    def test_list_value(self, sample_df: pd.DataFrame):
        result = DatasetManager._apply_filter(
            sample_df, {"status": ["active", "pending"]}
        )
        assert len(result) == 4
        assert "archived" not in result["status"].values

    def test_tuple_value(self, sample_df: pd.DataFrame):
        result = DatasetManager._apply_filter(
            sample_df, {"status": ("active", "pending")}
        )
        assert len(result) == 4

    def test_set_value(self, sample_df: pd.DataFrame):
        result = DatasetManager._apply_filter(
            sample_df, {"project": {"Pokemon", "YuGiOh"}}
        )
        assert len(result) == 3
        assert "Digimon" not in result["project"].values

    def test_multiple_keys_anded(self, sample_df: pd.DataFrame):
        result = DatasetManager._apply_filter(
            sample_df, {"project": "Pokemon", "status": "active"}
        )
        assert len(result) == 1
        assert result.iloc[0]["score"] == 10

    def test_empty_result(self, sample_df: pd.DataFrame):
        result = DatasetManager._apply_filter(
            sample_df, {"project": "Nonexistent"}
        )
        assert len(result) == 0
        assert list(result.columns) == ["project", "status", "score"]

    def test_missing_column_raises(self, sample_df: pd.DataFrame):
        with pytest.raises(ValueError, match="Filter column 'nonexistent' not found"):
            DatasetManager._apply_filter(sample_df, {"nonexistent": "value"})

    def test_missing_column_lists_available(self, sample_df: pd.DataFrame):
        with pytest.raises(ValueError, match="Available:"):
            DatasetManager._apply_filter(sample_df, {"bad_col": "x"})

    def test_empty_filter_dict_returns_unchanged(self, sample_df: pd.DataFrame):
        result = DatasetManager._apply_filter(sample_df, {})
        pd.testing.assert_frame_equal(
            result.reset_index(drop=True),
            sample_df.reset_index(drop=True),
        )

    def test_index_is_reset(self, sample_df: pd.DataFrame):
        result = DatasetManager._apply_filter(sample_df, {"project": "Digimon"})
        assert list(result.index) == [0, 1]


# ─────────────────────────────────────────────────────────────────────────────
# Integration tests for add_dataset with filter
# ─────────────────────────────────────────────────────────────────────────────

class TestAddDatasetFilter:

    @pytest.mark.asyncio
    async def test_add_dataset_with_filter(
        self, dm: DatasetManager, sample_df: pd.DataFrame
    ):
        result = await dm.add_dataset(
            name="filtered",
            dataframe=sample_df,
            filter={"project": "Pokemon"},
        )
        assert "2 rows" in result
        entry = dm._datasets["filtered"]
        assert len(entry._df) == 2
        assert list(entry._df["project"].unique()) == ["Pokemon"]

    @pytest.mark.asyncio
    async def test_add_dataset_with_list_filter(
        self, dm: DatasetManager, sample_df: pd.DataFrame
    ):
        result = await dm.add_dataset(
            name="multi_filter",
            dataframe=sample_df,
            filter={"status": ["active", "pending"]},
        )
        assert "4 rows" in result

    @pytest.mark.asyncio
    async def test_add_dataset_with_multi_key_filter(
        self, dm: DatasetManager, sample_df: pd.DataFrame
    ):
        result = await dm.add_dataset(
            name="multi_key",
            dataframe=sample_df,
            filter={"project": "Pokemon", "status": "active"},
        )
        assert "1 rows" in result

    @pytest.mark.asyncio
    async def test_add_dataset_no_filter_backward_compat(
        self, dm: DatasetManager, sample_df: pd.DataFrame
    ):
        result = await dm.add_dataset(
            name="unfiltered",
            dataframe=sample_df,
        )
        assert "5 rows" in result
        entry = dm._datasets["unfiltered"]
        assert len(entry._df) == 5

    @pytest.mark.asyncio
    async def test_add_dataset_filter_bad_column_raises(
        self, dm: DatasetManager, sample_df: pd.DataFrame
    ):
        with pytest.raises(ValueError, match="Filter column 'bad' not found"):
            await dm.add_dataset(
                name="bad",
                dataframe=sample_df,
                filter={"bad": "value"},
            )
