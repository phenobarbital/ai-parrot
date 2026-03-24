"""Unit tests for FEAT-059 — dataset description feature.

Covers:
- DatasetEntry description field (priority resolution, truncation, to_info)
- Registration methods accepting description parameter
- get_datasets_summary() format and filtering
- get_metadata() top-level description field
- _generate_dataframe_guide() / get_guide() dataset summary section
- Backward compatibility (no description param)
"""

import pytest
import pandas as pd

from parrot.tools.dataset_manager.tool import DatasetEntry, DatasetManager


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def dm() -> DatasetManager:
    """Return a fresh DatasetManager instance."""
    return DatasetManager()


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """Return a simple DataFrame for testing."""
    return pd.DataFrame(
        {"region": ["East", "West", "North"], "sales": [100, 200, 150]}
    )


# ─────────────────────────────────────────────────────────────────────────────
# TASK-415 — DatasetEntry description field
# ─────────────────────────────────────────────────────────────────────────────


class TestDatasetEntryDescription:
    """DatasetEntry correctly stores and resolves the description field."""

    def test_explicit_description(self, sample_df: pd.DataFrame) -> None:
        """Explicit description is stored as-is."""
        entry = DatasetEntry(name="test", description="My dataset", df=sample_df)
        assert entry.description == "My dataset"

    def test_metadata_fallback(self, sample_df: pd.DataFrame) -> None:
        """Falls back to metadata['description'] when no explicit description."""
        entry = DatasetEntry(
            name="test",
            metadata={"description": "From metadata"},
            df=sample_df,
        )
        assert entry.description == "From metadata"

    def test_explicit_overrides_metadata(self, sample_df: pd.DataFrame) -> None:
        """Explicit description takes priority over metadata['description']."""
        entry = DatasetEntry(
            name="test",
            description="Explicit",
            metadata={"description": "From metadata"},
            df=sample_df,
        )
        assert entry.description == "Explicit"

    def test_no_description_defaults_empty(self, sample_df: pd.DataFrame) -> None:
        """No description defaults to empty string."""
        entry = DatasetEntry(name="test", df=sample_df)
        assert entry.description == ""

    def test_truncation_at_300(self, sample_df: pd.DataFrame) -> None:
        """Description is truncated to 300 characters."""
        long_desc = "x" * 500
        entry = DatasetEntry(name="test", description=long_desc, df=sample_df)
        assert len(entry.description) == 300

    def test_to_info_includes_description(self, sample_df: pd.DataFrame) -> None:
        """to_info() populates DatasetInfo.description from entry.description."""
        entry = DatasetEntry(name="test", description="My dataset", df=sample_df)
        info = entry.to_info(alias="df1")
        assert info.description == "My dataset"

    def test_to_info_empty_description(self, sample_df: pd.DataFrame) -> None:
        """to_info() sets DatasetInfo.description to empty string when none set."""
        entry = DatasetEntry(name="test", df=sample_df)
        info = entry.to_info(alias="df1")
        assert info.description == ""


# ─────────────────────────────────────────────────────────────────────────────
# TASK-416 — Registration methods with description parameter
# ─────────────────────────────────────────────────────────────────────────────


class TestRegistrationMethods:
    """All add_* methods accept and forward the description parameter."""

    def test_add_dataframe_with_description(
        self, dm: DatasetManager, sample_df: pd.DataFrame
    ) -> None:
        """add_dataframe passes description to DatasetEntry."""
        dm.add_dataframe("sales", sample_df, description="Sales data")
        assert dm.get_dataset_entry("sales").description == "Sales data"

    def test_add_dataframe_without_description(
        self, dm: DatasetManager, sample_df: pd.DataFrame
    ) -> None:
        """add_dataframe without description defaults to empty string."""
        dm.add_dataframe("sales", sample_df)
        assert dm.get_dataset_entry("sales").description == ""

    def test_add_query_with_description(self, dm: DatasetManager) -> None:
        """add_query passes description to DatasetEntry."""
        dm.add_query("test", "some_slug", description="Query data")
        assert dm.get_dataset_entry("test").description == "Query data"

    def test_add_query_without_description(self, dm: DatasetManager) -> None:
        """add_query without description defaults to empty string."""
        dm.add_query("test", "some_slug")
        assert dm.get_dataset_entry("test").description == ""

    def test_add_sql_source_with_description(self, dm: DatasetManager) -> None:
        """add_sql_source passes description to DatasetEntry."""
        dm.add_sql_source("test", "SELECT 1", "pg", description="SQL data")
        assert dm.get_dataset_entry("test").description == "SQL data"

    def test_add_sql_source_without_description(self, dm: DatasetManager) -> None:
        """add_sql_source without description defaults to empty string."""
        dm.add_sql_source("test", "SELECT 1", "pg")
        assert dm.get_dataset_entry("test").description == ""

    def test_description_via_metadata_fallback(
        self, dm: DatasetManager, sample_df: pd.DataFrame
    ) -> None:
        """Passing description via metadata dict still works (backward compat)."""
        dm.add_dataframe("test", sample_df, metadata={"description": "Meta desc"})
        assert dm.get_dataset_entry("test").description == "Meta desc"

    def test_explicit_description_overrides_metadata(
        self, dm: DatasetManager, sample_df: pd.DataFrame
    ) -> None:
        """Explicit description overrides metadata description."""
        dm.add_dataframe(
            "test",
            sample_df,
            description="Explicit",
            metadata={"description": "From metadata"},
        )
        assert dm.get_dataset_entry("test").description == "Explicit"


# ─────────────────────────────────────────────────────────────────────────────
# TASK-417 — get_datasets_summary()
# ─────────────────────────────────────────────────────────────────────────────


class TestGetDatasetsSummary:
    """get_datasets_summary() returns a correct markdown bullet list."""

    @pytest.mark.asyncio
    async def test_summary_format(
        self, dm: DatasetManager, sample_df: pd.DataFrame
    ) -> None:
        """Summary contains all active datasets with descriptions."""
        dm.add_dataframe("sales", sample_df, description="Q4 sales")
        dm.add_dataframe("logs", sample_df)  # no description

        summary = await dm.get_datasets_summary()
        assert "- **sales**: Q4 sales" in summary
        assert "- **logs**: (no description)" in summary

    @pytest.mark.asyncio
    async def test_excludes_inactive(
        self, dm: DatasetManager, sample_df: pd.DataFrame
    ) -> None:
        """Inactive datasets are excluded from the summary."""
        dm.add_dataframe("sales", sample_df, description="Q4 sales")
        dm.add_dataframe("census", sample_df, description="US Census 2023")
        dm.deactivate("sales")

        summary = await dm.get_datasets_summary()
        assert "sales" not in summary
        assert "census" in summary

    @pytest.mark.asyncio
    async def test_empty_when_no_datasets(self, dm: DatasetManager) -> None:
        """Returns empty string when no datasets are registered."""
        summary = await dm.get_datasets_summary()
        assert summary == ""

    @pytest.mark.asyncio
    async def test_empty_when_all_inactive(
        self, dm: DatasetManager, sample_df: pd.DataFrame
    ) -> None:
        """Returns empty string when all datasets are inactive."""
        dm.add_dataframe("sales", sample_df, description="Q4 sales")
        dm.deactivate("sales")

        summary = await dm.get_datasets_summary()
        assert summary == ""


# ─────────────────────────────────────────────────────────────────────────────
# TASK-418 — get_metadata() and _generate_dataframe_guide()
# ─────────────────────────────────────────────────────────────────────────────


class TestMetadataDescription:
    """get_metadata() includes description as a top-level key."""

    @pytest.mark.asyncio
    async def test_get_metadata_includes_description(
        self, dm: DatasetManager, sample_df: pd.DataFrame
    ) -> None:
        """get_metadata() includes description at the top level."""
        dm.add_dataframe("sales", sample_df, description="Q4 sales by region")
        meta = await dm.get_metadata("sales")
        assert meta["description"] == "Q4 sales by region"

    @pytest.mark.asyncio
    async def test_get_metadata_empty_description(
        self, dm: DatasetManager, sample_df: pd.DataFrame
    ) -> None:
        """get_metadata() returns empty string when no description set."""
        dm.add_dataframe("test", sample_df)
        meta = await dm.get_metadata("test")
        assert meta["description"] == ""


class TestGuideDescription:
    """_generate_dataframe_guide() / get_guide() prepends dataset summary section."""

    def test_guide_includes_summary(
        self, dm: DatasetManager, sample_df: pd.DataFrame
    ) -> None:
        """Guide contains 'Available Datasets' section with descriptions."""
        dm.add_dataframe("sales", sample_df, description="Q4 sales by region")
        guide = dm.get_guide()
        assert "Available Datasets" in guide
        assert "**sales**: Q4 sales by region" in guide

    def test_guide_no_summary_when_no_datasets(self) -> None:
        """Guide omits summary section when no datasets are registered."""
        dm = DatasetManager()
        guide = dm.get_guide()
        assert "Available Datasets" not in guide

    def test_guide_no_description_shows_placeholder(
        self, dm: DatasetManager, sample_df: pd.DataFrame
    ) -> None:
        """Guide shows '(no description)' for datasets without a description."""
        dm.add_dataframe("logs", sample_df)
        guide = dm.get_guide()
        assert "(no description)" in guide

    def test_guide_regenerated_on_add(
        self, dm: DatasetManager, sample_df: pd.DataFrame
    ) -> None:
        """Guide is refreshed after each dataset addition."""
        dm.add_dataframe("sales", sample_df, description="First dataset")
        guide1 = dm.get_guide()
        assert "First dataset" in guide1

        dm.add_dataframe("census", sample_df, description="Second dataset")
        guide2 = dm.get_guide()
        assert "Second dataset" in guide2


# ─────────────────────────────────────────────────────────────────────────────
# Backward compatibility
# ─────────────────────────────────────────────────────────────────────────────


class TestBackwardCompatibility:
    """Existing code without description parameter continues to work."""

    def test_add_dataframe_no_description(
        self, dm: DatasetManager, sample_df: pd.DataFrame
    ) -> None:
        """add_dataframe without description still registers the dataset."""
        result = dm.add_dataframe("test", sample_df)
        assert "test" in result
        entry = dm.get_dataset_entry("test")
        assert entry is not None
        assert entry.description == ""

    def test_dataset_entry_no_description(self, sample_df: pd.DataFrame) -> None:
        """DatasetEntry without description parameter still works."""
        entry = DatasetEntry(name="test", df=sample_df)
        assert entry is not None
        assert entry.description == ""

    def test_metadata_description_still_works(
        self, dm: DatasetManager, sample_df: pd.DataFrame
    ) -> None:
        """Passing description via metadata dict remains backward compatible."""
        dm.add_dataframe("test", sample_df, metadata={"description": "Via metadata"})
        entry = dm.get_dataset_entry("test")
        assert entry.description == "Via metadata"
