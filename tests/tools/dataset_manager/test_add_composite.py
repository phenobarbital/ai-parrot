"""
Unit tests for DatasetManager.add_composite_dataset (TASK-432).

Tests cover:
- Basic registration
- Component validation (missing dataset raises ValueError)
- computed_columns passthrough
- Multiple joins confirmation message
- Join type reflected in confirmation message
"""
import pytest
import pandas as pd
from parrot.tools.dataset_manager.tool import DatasetManager
from parrot.tools.dataset_manager.computed import ComputedColumnDef


@pytest.fixture
def dm():
    dm = DatasetManager(generate_guide=False)
    dm.add_dataframe("sales", pd.DataFrame({
        "id": [1, 2], "revenue": [100, 200], "expenses": [60, 80],
    }))
    dm.add_dataframe("regions", pd.DataFrame({
        "id": [1, 2], "region": ["East", "West"],
    }))
    return dm


class TestAddCompositeDataset:
    def test_basic_registration(self, dm):
        result = dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
            description="Sales with regions",
        )
        assert "combined" in result
        assert "combined" in dm._datasets

    def test_missing_component_raises(self, dm):
        with pytest.raises(ValueError, match="not registered"):
            dm.add_composite_dataset(
                "bad",
                joins=[{"left": "sales", "right": "nonexistent", "on": "id"}],
            )

    def test_missing_left_component_raises(self, dm):
        with pytest.raises(ValueError, match="not registered"):
            dm.add_composite_dataset(
                "bad",
                joins=[{"left": "nonexistent", "right": "regions", "on": "id"}],
            )

    def test_with_computed_columns(self, dm):
        cols = [ComputedColumnDef(
            name="ebitda", func="math_operation",
            columns=["revenue", "expenses"],
            kwargs={"operation": "subtract"},
        )]
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
            computed_columns=cols,
        )
        entry = dm._datasets["combined"]
        assert len(entry._computed_columns) == 1

    def test_multiple_joins(self, dm):
        dm.add_dataframe("extra", pd.DataFrame({
            "id": [1, 2], "score": [9.5, 8.0],
        }))
        result = dm.add_composite_dataset(
            "full",
            joins=[
                {"left": "sales", "right": "regions", "on": "id"},
                {"left": "regions", "right": "extra", "on": "id"},
            ],
        )
        assert "2 join(s)" in result

    def test_confirmation_message(self, dm):
        result = dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id", "how": "left"}],
        )
        assert "LEFT JOIN" in result

    def test_inner_join_in_message(self, dm):
        result = dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
        )
        assert "INNER JOIN" in result

    def test_entry_stored_in_datasets(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
        )
        entry = dm._datasets["combined"]
        assert entry.name == "combined"

    def test_entry_source_is_composite(self, dm):
        from parrot.tools.dataset_manager.sources.composite import CompositeDataSource
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
        )
        entry = dm._datasets["combined"]
        assert isinstance(entry.source, CompositeDataSource)

    def test_is_active_passthrough(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
            is_active=False,
        )
        entry = dm._datasets["combined"]
        assert entry.is_active is False

    def test_metadata_passthrough(self, dm):
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
            metadata={"owner": "test"},
        )
        entry = dm._datasets["combined"]
        assert entry.metadata.get("owner") == "test"

    def test_join_spec_on_list(self, dm):
        """on can be a list of columns."""
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": ["id"]}],
        )
        assert "combined" in dm._datasets

    @pytest.mark.asyncio
    async def test_composite_materializes(self, dm):
        """Registered composite can be materialized via fetch."""
        dm.add_composite_dataset(
            "combined",
            joins=[{"left": "sales", "right": "regions", "on": "id"}],
        )
        entry = dm._datasets["combined"]
        result = await entry.source.fetch()
        assert "revenue" in result.columns
        assert "region" in result.columns
        assert len(result) == 2
