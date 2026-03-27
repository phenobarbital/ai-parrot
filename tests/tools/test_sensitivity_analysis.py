"""Unit tests for TASK-459: SensitivityAnalysisTool."""
import pytest
import pandas as pd
from parrot_tools.sensitivity_analysis import SensitivityAnalysisTool, SensitivityAnalysisInput
from parrot_tools.whatif import DerivedMetric


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        'revenue': [100000, 200000, 150000, 180000],
        'expenses': [80000, 150000, 120000, 140000],
        'kiosks': [50, 80, 60, 70],
        'warehouses': [3, 5, 4, 4],
    })


def _make_tool(df, df_name="test"):
    tool = SensitivityAnalysisTool()
    tool._parent_agent = type('Agent', (), {'dataframes': {df_name: df}})()
    return tool


class TestSensitivityAnalysis:
    @pytest.mark.asyncio
    async def test_ranks_by_impact(self, sample_df):
        tool = _make_tool(sample_df)
        result = await tool._execute(
            df_name="test", target_metric="revenue", variation_range=20.0
        )
        assert result.success
        assert "impact" in str(result.result).lower() or "revenue" in str(result.result).lower()

    @pytest.mark.asyncio
    async def test_with_derived_metric(self, sample_df):
        tool = _make_tool(sample_df)
        result = await tool._execute(
            df_name="test", target_metric="ebitda",
            derived_metrics=[DerivedMetric(name="ebitda", formula="revenue - expenses")],
            variation_range=20.0,
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_elasticity_is_one_for_self(self, sample_df):
        """When varying revenue and measuring revenue, elasticity should be ~1.0."""
        tool = _make_tool(sample_df)
        result = await tool._execute(
            df_name="test", target_metric="revenue",
            input_variables=["revenue"],
            variation_range=20.0,
        )
        assert result.success
        # Check elasticity is approximately 1.0
        meta = result.metadata["results"]
        assert len(meta) == 1
        assert abs(meta[0]["elasticity"] - 1.0) < 0.01

    @pytest.mark.asyncio
    async def test_auto_detect_variables(self, sample_df):
        tool = _make_tool(sample_df)
        result = await tool._execute(
            df_name="test", target_metric="revenue", variation_range=10.0
        )
        assert result.success
        # Should analyze expenses, kiosks, warehouses (not revenue itself)
        meta = result.metadata["results"]
        names = [r["variable"] for r in meta]
        assert "revenue" not in names
        assert "expenses" in names

    @pytest.mark.asyncio
    async def test_dataset_not_found(self):
        tool = SensitivityAnalysisTool()
        result = await tool._execute(
            df_name="nonexistent", target_metric="x", variation_range=10.0
        )
        assert not result.success

    @pytest.mark.asyncio
    async def test_invalid_target_metric(self, sample_df):
        tool = _make_tool(sample_df)
        result = await tool._execute(
            df_name="test", target_metric="nonexistent", variation_range=10.0
        )
        assert not result.success

    @pytest.mark.asyncio
    async def test_sorted_by_range(self, sample_df):
        tool = _make_tool(sample_df)
        result = await tool._execute(
            df_name="test", target_metric="revenue", variation_range=20.0
        )
        meta = result.metadata["results"]
        ranges = [r["range"] for r in meta]
        assert ranges == sorted(ranges, reverse=True)
