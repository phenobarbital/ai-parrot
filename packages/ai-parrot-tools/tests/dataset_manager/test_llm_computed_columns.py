"""
Unit tests for LLM runtime computed columns methods (TASK-430).

Tests cover:
- add_computed_column() validation (function, dataset, columns)
- add_computed_column() immediate application when loaded
- add_computed_column() returns confirmation message
- list_available_functions() returns sorted list
"""
import pytest
import pandas as pd
from parrot.tools.dataset_manager.tool import DatasetManager


@pytest.fixture
def dm():
    dm = DatasetManager(generate_guide=False)
    df = pd.DataFrame({"revenue": [100.0, 200.0], "expenses": [60.0, 80.0]})
    dm.add_dataframe("sales", df)
    return dm


class TestAddComputedColumn:
    @pytest.mark.asyncio
    async def test_add_valid_column(self, dm):
        result = await dm.add_computed_column(
            "sales", "ebitda", "math_operation",
            ["revenue", "expenses"], operation="subtract",
        )
        assert "ebitda" in result
        assert "added" in result.lower()
        assert "ebitda" in dm._datasets["sales"]._df.columns

    @pytest.mark.asyncio
    async def test_add_valid_column_values(self, dm):
        await dm.add_computed_column(
            "sales", "ebitda", "math_operation",
            ["revenue", "expenses"], operation="subtract",
        )
        df = dm._datasets["sales"]._df
        assert list(df["ebitda"]) == [40.0, 120.0]

    @pytest.mark.asyncio
    async def test_unknown_function(self, dm):
        result = await dm.add_computed_column(
            "sales", "x", "nonexistent_function", ["revenue"],
        )
        assert "Unknown function" in result

    @pytest.mark.asyncio
    async def test_unknown_dataset(self, dm):
        result = await dm.add_computed_column(
            "missing_dataset", "x", "math_operation", ["a", "b"],
        )
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_missing_columns(self, dm):
        result = await dm.add_computed_column(
            "sales", "x", "math_operation",
            ["revenue", "nonexistent_column"], operation="add",
        )
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_column_stored_in_entry(self, dm):
        await dm.add_computed_column(
            "sales", "ebitda", "math_operation",
            ["revenue", "expenses"], operation="subtract",
        )
        entry = dm._datasets["sales"]
        assert any(c.name == "ebitda" for c in entry._computed_columns)

    @pytest.mark.asyncio
    async def test_description_stored(self, dm):
        await dm.add_computed_column(
            "sales", "ebitda", "math_operation",
            ["revenue", "expenses"],
            description="Earnings metric",
            operation="subtract",
        )
        entry = dm._datasets["sales"]
        col_def = next(c for c in entry._computed_columns if c.name == "ebitda")
        assert col_def.description == "Earnings metric"

    @pytest.mark.asyncio
    async def test_add_to_unloaded_dataset(self):
        """Adding to unloaded dataset stores definition but doesn't apply immediately."""
        from parrot.tools.dataset_manager.sources.sql import SQLQuerySource
        from parrot.tools.dataset_manager.tool import DatasetEntry

        dm = DatasetManager(generate_guide=False)
        source = SQLQuerySource(sql="SELECT 1", driver="pg")
        entry = DatasetEntry(name="lazy", source=source)
        dm._datasets["lazy"] = entry

        result = await dm.add_computed_column(
            "lazy", "x", "math_operation", ["a", "b"],
        )
        # Should not fail validation (no known columns to check)
        assert "lazy" in result or "x" in result


class TestListAvailableFunctions:
    @pytest.mark.asyncio
    async def test_returns_sorted_list(self, dm):
        fns = await dm.list_available_functions()
        assert isinstance(fns, list)
        assert fns == sorted(fns)
        assert "math_operation" in fns
        assert "concatenate" in fns

    @pytest.mark.asyncio
    async def test_returns_non_empty_list(self, dm):
        fns = await dm.list_available_functions()
        assert len(fns) >= 2  # at least math_operation and concatenate
