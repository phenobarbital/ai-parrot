"""Unit tests for TASK-463: BreakEvenAnalysisTool."""
import pytest
import pandas as pd
import numpy as np
from parrot_tools.breakeven import BreakEvenAnalysisTool
from parrot_tools.whatif import DerivedMetric


@pytest.fixture
def pokemon_df():
    return pd.DataFrame({
        'Project': ['A', 'B', 'C', 'D', 'E'],
        'revenue': [500000, 800000, 300000, 400000, 350000],
        'expenses': [400000, 600000, 250000, 350000, 300000],
        'kiosks': [50, 80, 30, 40, 35],
        'warehouses': [3, 5, 2, 3, 2],
    })


def _make_tool(df, df_name="test"):
    tool = BreakEvenAnalysisTool()
    tool._parent_agent = type('Agent', (), {'dataframes': {df_name: df}})()
    return tool


class TestBreakEven:
    @pytest.mark.asyncio
    async def test_simple_breakeven(self, pokemon_df):
        """Find break-even revenue for a target (self-referential works)."""
        tool = _make_tool(pokemon_df)
        result = await tool._execute(
            df_name="test",
            target_metric="revenue",
            target_value=3000000,
            variable="revenue",
        )
        assert result.success
        assert result.metadata["breakeven_value"] is not None

    @pytest.mark.asyncio
    async def test_breakeven_with_derived_metric(self, pokemon_df):
        tool = _make_tool(pokemon_df)
        result = await tool._execute(
            df_name="test",
            target_metric="ebitda",
            target_value=0,
            variable="kiosks",
            derived_metrics=[DerivedMetric(name="ebitda", formula="revenue - expenses")],
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_breakeven_with_fixed_changes(self, pokemon_df):
        """Break-even kiosks after adding warehouses (increases expenses)."""
        tool = _make_tool(pokemon_df)
        result = await tool._execute(
            df_name="test",
            target_metric="ebitda",
            target_value=0,
            variable="kiosks",
            fixed_changes={"expenses": 45000},
            derived_metrics=[DerivedMetric(name="ebitda", formula="revenue - expenses")],
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_sensitivity_curve_included(self, pokemon_df):
        tool = _make_tool(pokemon_df)
        result = await tool._execute(
            df_name="test",
            target_metric="revenue",
            target_value=3000000,
            variable="revenue",
        )
        assert result.success
        assert "sensitivity" in str(result.result).lower() or "curve" in str(result.result).lower()
        assert len(result.metadata["sensitivity_curve"]) > 0

    @pytest.mark.asyncio
    async def test_no_root_found(self, pokemon_df):
        """Target value impossible to reach in range."""
        tool = _make_tool(pokemon_df)
        result = await tool._execute(
            df_name="test",
            target_metric="revenue",
            target_value=-1000000,
            variable="kiosks",
            variable_range=[0.1, 500],
        )
        assert result.success  # succeeds but reports no root
        assert "not found" in str(result.result).lower() or "no break-even" in str(result.result).lower()

    @pytest.mark.asyncio
    async def test_dataset_not_found(self):
        tool = BreakEvenAnalysisTool()
        result = await tool._execute(
            df_name="nonexistent",
            target_metric="x",
            target_value=0,
            variable="y",
        )
        assert not result.success

    @pytest.mark.asyncio
    async def test_invalid_variable(self, pokemon_df):
        tool = _make_tool(pokemon_df)
        result = await tool._execute(
            df_name="test",
            target_metric="revenue",
            target_value=0,
            variable="nonexistent",
        )
        assert not result.success

    @pytest.mark.asyncio
    async def test_margin_of_safety(self, pokemon_df):
        tool = _make_tool(pokemon_df)
        result = await tool._execute(
            df_name="test",
            target_metric="revenue",
            target_value=3000000,
            variable="revenue",
        )
        assert result.success
        if result.metadata["breakeven_value"]:
            assert "Margin" in str(result.result) or "margin" in str(result.result).lower()
