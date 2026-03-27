"""Unit tests for TASK-461: StatisticalTestsTool."""
import pytest
import pandas as pd
import numpy as np
from parrot_tools.statistical_tests import StatisticalTestsTool


@pytest.fixture
def df_with_groups():
    """DataFrame with known significant difference between groups."""
    np.random.seed(42)
    return pd.DataFrame({
        'Region': ['North'] * 50 + ['South'] * 50,
        'Revenue': list(np.random.normal(1000, 100, 50)) + list(np.random.normal(800, 100, 50)),
        'Category': ['A'] * 30 + ['B'] * 20 + ['A'] * 20 + ['B'] * 30,
    })


def _make_tool(df, df_name="test"):
    tool = StatisticalTestsTool()
    tool._parent_agent = type('Agent', (), {'dataframes': {df_name: df}})()
    return tool


class TestStatisticalTests:
    @pytest.mark.asyncio
    async def test_ttest_detects_significant_difference(self, df_with_groups):
        tool = _make_tool(df_with_groups)
        result = await tool._execute(
            df_name="test", test_type="ttest",
            target_column="Revenue", group_column="Region"
        )
        assert result.success
        assert "significant" in str(result.result).lower()

    @pytest.mark.asyncio
    async def test_anova_with_groups(self, df_with_groups):
        tool = _make_tool(df_with_groups)
        result = await tool._execute(
            df_name="test", test_type="anova",
            target_column="Revenue", group_column="Region"
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_normality_check(self, df_with_groups):
        tool = _make_tool(df_with_groups)
        result = await tool._execute(
            df_name="test", test_type="normality",
            target_column="Revenue"
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_chi_square(self, df_with_groups):
        tool = _make_tool(df_with_groups)
        result = await tool._execute(
            df_name="test", test_type="chi_square",
            target_column="Category", group_column="Region"
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_mann_whitney(self, df_with_groups):
        tool = _make_tool(df_with_groups)
        result = await tool._execute(
            df_name="test", test_type="mann_whitney",
            target_column="Revenue", group_column="Region"
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_kruskal_wallis(self, df_with_groups):
        tool = _make_tool(df_with_groups)
        result = await tool._execute(
            df_name="test", test_type="kruskal_wallis",
            target_column="Revenue", group_column="Region"
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_unknown_test_type(self, df_with_groups):
        tool = _make_tool(df_with_groups)
        result = await tool._execute(
            df_name="test", test_type="unknown",
            target_column="Revenue"
        )
        assert not result.success

    @pytest.mark.asyncio
    async def test_ttest_effect_size(self, df_with_groups):
        tool = _make_tool(df_with_groups)
        result = await tool._execute(
            df_name="test", test_type="ttest",
            target_column="Revenue", group_column="Region"
        )
        assert result.success
        assert "Cohen's d" in str(result.result)

    @pytest.mark.asyncio
    async def test_dataset_not_found(self):
        tool = StatisticalTestsTool()
        result = await tool._execute(
            df_name="nonexistent", test_type="ttest",
            target_column="x", group_column="g"
        )
        assert not result.success
