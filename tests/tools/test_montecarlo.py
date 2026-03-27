"""Unit tests for TASK-460: MonteCarloSimulationTool."""
import pytest
import pandas as pd
import numpy as np
from parrot_tools.montecarlo import MonteCarloSimulationTool, MonteCarloInput, VariableDistribution
from parrot_tools.whatif import DerivedMetric


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        'revenue': [100000, 200000, 150000, 180000],
        'expenses': [80000, 150000, 120000, 140000],
        'kiosks': [50, 80, 60, 70],
    })


def _make_tool(df, df_name="test"):
    tool = MonteCarloSimulationTool()
    tool._parent_agent = type('Agent', (), {'dataframes': {df_name: df}})()
    return tool


class TestMonteCarlo:
    @pytest.mark.asyncio
    async def test_uniform_distribution(self, sample_df):
        tool = _make_tool(sample_df)
        result = await tool._execute(
            df_name="test",
            target_metrics=["revenue"],
            variables=[VariableDistribution(
                column="kiosks", distribution="uniform",
                params={"min_pct": -20, "max_pct": 20}
            )],
            n_simulations=5000,
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_normal_distribution(self, sample_df):
        tool = _make_tool(sample_df)
        result = await tool._execute(
            df_name="test",
            target_metrics=["revenue"],
            variables=[VariableDistribution(
                column="kiosks", distribution="normal",
                params={"mean_pct": 0, "std_pct": 10}
            )],
            n_simulations=5000,
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_triangular_distribution(self, sample_df):
        tool = _make_tool(sample_df)
        result = await tool._execute(
            df_name="test",
            target_metrics=["revenue"],
            variables=[VariableDistribution(
                column="kiosks", distribution="triangular",
                params={"min_pct": -10, "mode_pct": 5, "max_pct": 20}
            )],
            n_simulations=2000,
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_with_derived_metrics(self, sample_df):
        tool = _make_tool(sample_df)
        result = await tool._execute(
            df_name="test",
            target_metrics=["ebitda"],
            variables=[VariableDistribution(
                column="revenue", distribution="normal",
                params={"mean_pct": 10, "std_pct": 5}
            )],
            derived_metrics=[DerivedMetric(name="ebitda", formula="revenue - expenses")],
            n_simulations=5000,
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_rejects_too_many_simulations(self, sample_df):
        tool = _make_tool(sample_df)
        result = await tool._execute(
            df_name="test",
            target_metrics=["revenue"],
            variables=[VariableDistribution(
                column="kiosks", distribution="uniform",
                params={"min_pct": -10, "max_pct": 10}
            )],
            n_simulations=200000,
        )
        assert not result.success

    @pytest.mark.asyncio
    async def test_rejects_too_few_simulations(self, sample_df):
        tool = _make_tool(sample_df)
        result = await tool._execute(
            df_name="test",
            target_metrics=["revenue"],
            variables=[VariableDistribution(
                column="kiosks", distribution="uniform",
                params={"min_pct": -10, "max_pct": 10}
            )],
            n_simulations=10,
        )
        assert not result.success

    @pytest.mark.asyncio
    async def test_invalid_column(self, sample_df):
        tool = _make_tool(sample_df)
        result = await tool._execute(
            df_name="test",
            target_metrics=["revenue"],
            variables=[VariableDistribution(
                column="nonexistent", distribution="normal",
                params={"mean_pct": 0, "std_pct": 10}
            )],
            n_simulations=1000,
        )
        assert not result.success

    @pytest.mark.asyncio
    async def test_percentile_data_in_metadata(self, sample_df):
        tool = _make_tool(sample_df)
        result = await tool._execute(
            df_name="test",
            target_metrics=["revenue"],
            variables=[VariableDistribution(
                column="kiosks", distribution="uniform",
                params={"min_pct": -20, "max_pct": 20}
            )],
            n_simulations=2000,
        )
        assert result.success
        assert "percentiles" in result.metadata
        assert "revenue" in result.metadata["percentiles"]
        pdata = result.metadata["percentiles"]["revenue"]
        assert "P50" in pdata
        assert "mean" in pdata

    @pytest.mark.asyncio
    async def test_multiple_metrics(self, sample_df):
        tool = _make_tool(sample_df)
        result = await tool._execute(
            df_name="test",
            target_metrics=["revenue", "expenses"],
            variables=[VariableDistribution(
                column="kiosks", distribution="uniform",
                params={"min_pct": -10, "max_pct": 10}
            )],
            n_simulations=1000,
        )
        assert result.success
        assert "revenue" in result.metadata["percentiles"]
        assert "expenses" in result.metadata["percentiles"]
