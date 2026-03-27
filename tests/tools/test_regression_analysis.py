"""Unit tests for TASK-462: RegressionAnalysisTool."""
import pytest
import pandas as pd
import numpy as np
from parrot_tools.regression_analysis import RegressionAnalysisTool


@pytest.fixture
def linear_df():
    """DataFrame with known linear relationship: y = 2x + 10 + noise."""
    np.random.seed(42)
    x = np.linspace(10, 100, 50)
    y = 2 * x + 10 + np.random.normal(0, 5, 50)
    return pd.DataFrame({'kiosks': x, 'revenue': y})


@pytest.fixture
def multi_predictor_df():
    np.random.seed(42)
    n = 100
    kiosks = np.random.uniform(20, 100, n)
    warehouses = np.random.uniform(2, 10, n)
    revenue = 1250 * kiosks - 45000 * warehouses + 125000 + np.random.normal(0, 10000, n)
    return pd.DataFrame({'kiosks': kiosks, 'warehouses': warehouses, 'revenue': revenue})


def _make_tool(df, df_name="test"):
    tool = RegressionAnalysisTool()
    tool._parent_agent = type('Agent', (), {'dataframes': {df_name: df}})()
    return tool


class TestRegressionAnalysis:
    @pytest.mark.asyncio
    async def test_linear_coefficient_accuracy(self, linear_df):
        tool = _make_tool(linear_df)
        result = await tool._execute(
            df_name="test", target="revenue", predictors=["kiosks"],
            model_type="linear"
        )
        assert result.success
        assert "kiosks" in str(result.result)
        # Coefficient should be close to 2.0
        coeff = result.metadata["coefficients"]["kiosks"]
        assert abs(coeff - 2.0) < 0.5

    @pytest.mark.asyncio
    async def test_r_squared_high_for_linear(self, linear_df):
        tool = _make_tool(linear_df)
        result = await tool._execute(
            df_name="test", target="revenue", predictors=["kiosks"]
        )
        assert result.success
        assert result.metadata["r_squared"] > 0.9

    @pytest.mark.asyncio
    async def test_prediction_at_value(self, linear_df):
        tool = _make_tool(linear_df)
        result = await tool._execute(
            df_name="test", target="revenue", predictors=["kiosks"],
            predict_at={"kiosks": 50.0}
        )
        assert result.success
        assert "Prediction" in str(result.result)

    @pytest.mark.asyncio
    async def test_multiple_predictors(self, multi_predictor_df):
        tool = _make_tool(multi_predictor_df)
        result = await tool._execute(
            df_name="test", target="revenue",
            predictors=["kiosks", "warehouses"]
        )
        assert result.success
        assert result.metadata["r_squared"] > 0.7

    @pytest.mark.asyncio
    async def test_polynomial_regression(self, linear_df):
        tool = _make_tool(linear_df)
        result = await tool._execute(
            df_name="test", target="revenue", predictors=["kiosks"],
            model_type="polynomial"
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_log_regression(self, linear_df):
        tool = _make_tool(linear_df)
        result = await tool._execute(
            df_name="test", target="revenue", predictors=["kiosks"],
            model_type="log"
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_missing_column(self, linear_df):
        tool = _make_tool(linear_df)
        result = await tool._execute(
            df_name="test", target="revenue", predictors=["nonexistent"]
        )
        assert not result.success

    @pytest.mark.asyncio
    async def test_dataset_not_found(self):
        tool = RegressionAnalysisTool()
        result = await tool._execute(
            df_name="nonexistent", target="y", predictors=["x"]
        )
        assert not result.success

    @pytest.mark.asyncio
    async def test_coefficients_table(self, linear_df):
        tool = _make_tool(linear_df)
        result = await tool._execute(
            df_name="test", target="revenue", predictors=["kiosks"],
            include_diagnostics=True
        )
        assert result.success
        assert "Predictor" in str(result.result)
        assert "Significant" in str(result.result)
