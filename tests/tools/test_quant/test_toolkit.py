"""Unit tests for QuantToolkit main class."""

import pytest
import numpy as np
from parrot.tools.quant import QuantToolkit


@pytest.fixture
def toolkit():
    """Create QuantToolkit instance."""
    return QuantToolkit()


@pytest.fixture
def sample_returns():
    """100 days of simulated returns."""
    np.random.seed(42)
    return list(np.random.normal(0.001, 0.02, 100))


@pytest.fixture
def sample_benchmark_returns():
    """Benchmark returns (correlated with sample)."""
    np.random.seed(43)
    return list(np.random.normal(0.0008, 0.015, 100))


@pytest.fixture
def sample_price_data():
    """Price data for multiple assets."""
    np.random.seed(42)
    n = 100
    return {
        "AAPL": list(100 * np.cumprod(1 + np.random.normal(0.001, 0.02, n))),
        "MSFT": list(100 * np.cumprod(1 + np.random.normal(0.0012, 0.018, n))),
        "SPY": list(100 * np.cumprod(1 + np.random.normal(0.0008, 0.015, n))),
    }


@pytest.fixture
def sample_portfolio():
    """Sample portfolio for stress testing."""
    return {
        "SPY": 50000.0,
        "BTC": 30000.0,
        "TLT": 20000.0,
    }


# =============================================================================
# TOOLKIT STRUCTURE TESTS
# =============================================================================


class TestToolkitStructure:
    """Tests for QuantToolkit structure and inheritance."""

    def test_inherits_abstracttoolkit(self, toolkit):
        """QuantToolkit inherits from AbstractToolkit."""
        from parrot.tools.toolkit import AbstractToolkit
        assert isinstance(toolkit, AbstractToolkit)

    def test_toolkit_name(self, toolkit):
        """Toolkit has correct name."""
        assert toolkit.name == "quant_toolkit"

    @pytest.mark.asyncio
    async def test_get_tools_returns_all_methods(self, toolkit):
        """get_tools() returns all expected tools."""
        tools = await toolkit.get_tools()
        tool_names = [t.name for t in tools]

        expected = [
            "compute_risk_metrics",
            "compute_portfolio_risk",
            "compute_rolling_metrics",
            "compute_correlation_matrix",
            "detect_correlation_regimes",
            "compute_cross_asset_correlation",
            "calculate_piotroski_score",
            "batch_piotroski_scores",
            "compute_realized_volatility",
            "compute_volatility_cone",
            "compute_iv_rv_spread",
            "stress_test_portfolio",
        ]

        for name in expected:
            assert name in tool_names, f"Missing tool: {name}"

    @pytest.mark.asyncio
    async def test_get_tools_count(self, toolkit):
        """get_tools() returns exactly 12 tools."""
        tools = await toolkit.get_tools()
        assert len(tools) == 12

    @pytest.mark.asyncio
    async def test_tools_have_descriptions(self, toolkit):
        """All tools have docstring descriptions."""
        tools = await toolkit.get_tools()
        for tool in tools:
            assert tool.description, f"Tool {tool.name} missing description"
            assert len(tool.description) > 20, f"Tool {tool.name} description too short"

    @pytest.mark.asyncio
    async def test_get_tool_by_name(self, toolkit):
        """get_tool() returns correct tool."""
        # Trigger tool generation
        await toolkit.get_tools()
        tool = toolkit.get_tool("compute_risk_metrics")
        assert tool is not None
        assert tool.name == "compute_risk_metrics"

    @pytest.mark.asyncio
    async def test_list_tool_names(self, toolkit):
        """list_tool_names() returns all names."""
        # Trigger tool generation
        await toolkit.get_tools()
        names = toolkit.list_tool_names()
        assert "compute_risk_metrics" in names
        assert "stress_test_portfolio" in names
        assert len(names) == 12


# =============================================================================
# RISK METRICS TESTS
# =============================================================================


class TestRiskMetrics:
    """Tests for risk metrics methods."""

    @pytest.mark.asyncio
    async def test_compute_risk_metrics(self, toolkit, sample_returns):
        """compute_risk_metrics returns expected structure."""
        result = await toolkit.compute_risk_metrics(sample_returns)
        assert "volatility_annual" in result
        assert "sharpe_ratio" in result
        assert "var_95" in result
        assert "var_99" in result
        assert "cvar_95" in result
        assert "max_drawdown" in result

    @pytest.mark.asyncio
    async def test_compute_risk_metrics_with_benchmark(
        self, toolkit, sample_returns, sample_benchmark_returns
    ):
        """compute_risk_metrics calculates beta with benchmark."""
        result = await toolkit.compute_risk_metrics(
            returns=sample_returns,
            benchmark_returns=sample_benchmark_returns,
        )
        assert "beta" in result
        assert result["beta"] is not None

    @pytest.mark.asyncio
    async def test_compute_portfolio_risk(self, toolkit):
        """compute_portfolio_risk works with portfolio data."""
        np.random.seed(42)
        returns_data = {
            "AAPL": list(np.random.normal(0.001, 0.02, 60)),
            "SPY": list(np.random.normal(0.0008, 0.015, 60)),
        }
        result = await toolkit.compute_portfolio_risk(
            returns_data=returns_data,
            weights=[0.6, 0.4],
            symbols=["AAPL", "SPY"],
        )
        assert "portfolio_volatility" in result
        assert "var_1d_95_pct" in result
        assert "portfolio_sharpe" in result
        assert "max_drawdown" in result

    @pytest.mark.asyncio
    async def test_compute_rolling_metrics(self, toolkit, sample_returns):
        """compute_rolling_metrics returns rolling series."""
        result = await toolkit.compute_rolling_metrics(
            returns=sample_returns,
            window=20,
        )
        assert "rolling_vol" in result
        assert "rolling_sharpe" in result
        assert "rolling_var_95" in result
        assert isinstance(result["rolling_vol"], list)
        assert len(result["rolling_vol"]) > 0


# =============================================================================
# CORRELATION TESTS
# =============================================================================


class TestCorrelation:
    """Tests for correlation methods."""

    @pytest.mark.asyncio
    async def test_compute_correlation_matrix(self, toolkit, sample_price_data):
        """compute_correlation_matrix returns matrix."""
        result = await toolkit.compute_correlation_matrix(sample_price_data)
        assert "matrix" in result
        assert "method" in result
        assert "returns_based" in result
        assert "AAPL" in result["matrix"]
        assert "MSFT" in result["matrix"]["AAPL"]

    @pytest.mark.asyncio
    async def test_compute_correlation_matrix_methods(self, toolkit, sample_price_data):
        """Different correlation methods work."""
        for method in ["pearson", "spearman", "kendall"]:
            result = await toolkit.compute_correlation_matrix(
                sample_price_data, method=method
            )
            assert result["method"] == method

    @pytest.mark.asyncio
    async def test_detect_correlation_regimes(self, toolkit, sample_price_data):
        """detect_correlation_regimes returns regime alerts."""
        result = await toolkit.detect_correlation_regimes(
            price_data=sample_price_data,
            short_window=20,
            long_window=60,
        )
        assert "regime_alerts" in result
        assert "correlation_matrix_short" in result
        assert "correlation_matrix_long" in result

    @pytest.mark.asyncio
    async def test_compute_cross_asset_correlation(self, toolkit):
        """compute_cross_asset_correlation handles calendar alignment."""
        np.random.seed(42)
        # Equity: weekdays only (roughly 70% of days)
        equity_prices = {
            "SPY": list(100 * np.cumprod(1 + np.random.normal(0.001, 0.015, 70))),
        }
        # Crypto: all days
        crypto_prices = {
            "BTC": list(50000 * np.cumprod(1 + np.random.normal(0.002, 0.04, 100))),
        }
        # Generate date strings
        from datetime import datetime, timedelta
        base_date = datetime(2024, 1, 1)
        timestamps_equity = [
            (base_date + timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(70)
        ]
        timestamps_crypto = [
            (base_date + timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(100)
        ]
        result = await toolkit.compute_cross_asset_correlation(
            equity_prices=equity_prices,
            crypto_prices=crypto_prices,
            timestamps_equity=timestamps_equity,
            timestamps_crypto=timestamps_crypto,
        )
        assert "cross_asset_correlations" in result
        assert "common_dates_count" in result


# =============================================================================
# PIOTROSKI TESTS
# =============================================================================


class TestPiotroski:
    """Tests for Piotroski F-Score methods."""

    @pytest.mark.asyncio
    async def test_calculate_piotroski_score(self, toolkit):
        """calculate_piotroski_score returns score."""
        result = await toolkit.calculate_piotroski_score(
            quarterly_financials={
                "net_income": 10_000_000,
                "total_assets": 50_000_000,
                "operating_cash_flow": 12_000_000,
            },
            prior_year_financials={},
        )
        assert "total_score" in result
        assert 0 <= result["total_score"] <= 9
        assert "criteria" in result
        assert "interpretation" in result

    @pytest.mark.asyncio
    async def test_calculate_piotroski_score_full(self, toolkit):
        """calculate_piotroski_score with full data."""
        result = await toolkit.calculate_piotroski_score(
            quarterly_financials={
                "net_income": 10_000_000,
                "total_assets": 50_000_000,
                "total_assets_prior": 48_000_000,
                "operating_cash_flow": 12_000_000,
                "total_debt": 15_000_000,
                "current_assets": 20_000_000,
                "current_liabilities": 10_000_000,
                "shares_outstanding": 1_000_000,
                "revenue": 100_000_000,
                "cost_of_revenue": 60_000_000,
            },
            prior_year_financials={
                "total_debt": 18_000_000,
                "current_ratio": 1.8,
                "shares_outstanding": 1_000_000,
                "gross_margin": 0.38,
                "asset_turnover": 1.9,
            },
        )
        assert result["total_score"] >= 4  # Should score well with good fundamentals

    @pytest.mark.asyncio
    async def test_batch_piotroski_scores(self, toolkit):
        """batch_piotroski_scores processes multiple stocks."""
        result = await toolkit.batch_piotroski_scores({
            "AAPL": {
                "quarterly_financials": {
                    "net_income": 20_000_000,
                    "total_assets": 100_000_000,
                    "operating_cash_flow": 25_000_000,
                },
                "prior_year_financials": {},
            },
            "MSFT": {
                "quarterly_financials": {
                    "net_income": 15_000_000,
                    "total_assets": 80_000_000,
                    "operating_cash_flow": 18_000_000,
                },
                "prior_year_financials": {},
            },
        })
        assert "AAPL" in result
        assert "MSFT" in result
        assert "total_score" in result["AAPL"]


# =============================================================================
# VOLATILITY TESTS
# =============================================================================


class TestVolatility:
    """Tests for volatility methods."""

    @pytest.mark.asyncio
    async def test_compute_realized_volatility(self, toolkit, sample_returns):
        """compute_realized_volatility returns vol series."""
        result = await toolkit.compute_realized_volatility(
            returns=sample_returns,
            window=20,
        )
        assert isinstance(result, list)
        assert len(result) > 0
        assert all(v >= 0 for v in result)

    @pytest.mark.asyncio
    async def test_compute_volatility_cone(self, toolkit, sample_returns):
        """compute_volatility_cone returns cone data."""
        result = await toolkit.compute_volatility_cone(
            returns=sample_returns,
            windows=[10, 20, 30],
        )
        assert isinstance(result, dict)
        assert 20 in result
        assert "current" in result[20]
        assert "percentile" in result[20]
        assert "min" in result[20]
        assert "max" in result[20]

    @pytest.mark.asyncio
    async def test_compute_iv_rv_spread(self, toolkit):
        """compute_iv_rv_spread returns spread analysis."""
        rv_series = [0.25] * 60
        result = await toolkit.compute_iv_rv_spread(
            implied_vol=0.30,
            realized_vol_series=rv_series,
        )
        assert "implied_vol" in result
        assert "realized_vol" in result
        assert "spread" in result
        assert "spread_pct" in result
        assert "regime" in result
        assert result["regime"] in ["fear_premium", "complacent", "normal"]


# =============================================================================
# STRESS TESTING TESTS
# =============================================================================


class TestStressTesting:
    """Tests for stress testing methods."""

    @pytest.mark.asyncio
    async def test_stress_test_portfolio_predefined(self, toolkit, sample_portfolio):
        """stress_test_portfolio with predefined scenarios."""
        result = await toolkit.stress_test_portfolio(
            portfolio_values=sample_portfolio,
            scenario_names=["covid_crash_2020"],
        )
        assert "scenario_results" in result
        assert "covid_crash_2020" in result["scenario_results"]
        assert "worst_scenario" in result
        assert "max_loss_pct" in result

    @pytest.mark.asyncio
    async def test_stress_test_portfolio_custom(self, toolkit, sample_portfolio):
        """stress_test_portfolio with custom scenario."""
        result = await toolkit.stress_test_portfolio(
            portfolio_values=sample_portfolio,
            custom_scenarios=[
                {
                    "name": "my_crash",
                    "asset_shocks": {"SPY": -0.20, "BTC": -0.40, "TLT": 0.05},
                }
            ],
        )
        assert "my_crash" in result["scenario_results"]

    @pytest.mark.asyncio
    async def test_stress_test_portfolio_default(self, toolkit, sample_portfolio):
        """stress_test_portfolio uses all predefined if no scenarios specified."""
        result = await toolkit.stress_test_portfolio(
            portfolio_values=sample_portfolio,
        )
        # Should have multiple scenarios
        assert len(result["scenario_results"]) >= 4

    @pytest.mark.asyncio
    async def test_stress_test_portfolio_results_structure(self, toolkit, sample_portfolio):
        """stress_test_portfolio returns correct result structure."""
        result = await toolkit.stress_test_portfolio(
            portfolio_values=sample_portfolio,
            scenario_names=["covid_crash_2020"],
        )
        scenario = result["scenario_results"]["covid_crash_2020"]
        assert "portfolio_loss_pct" in scenario
        assert "portfolio_loss_usd" in scenario
        assert "position_impacts" in scenario
        assert "worst_position" in scenario
        assert "best_position" in scenario


# =============================================================================
# IMPORT TESTS
# =============================================================================


class TestImports:
    """Tests for package imports."""

    def test_import_from_package(self):
        """Can import QuantToolkit from package."""
        from parrot.tools.quant import QuantToolkit
        assert QuantToolkit is not None

    def test_import_models(self):
        """Can import models from package."""
        from parrot.tools.quant import (
            PortfolioRiskInput,
            AssetRiskInput,
            CorrelationInput,
            StressScenario,
            PiotroskiInput,
        )
        assert PortfolioRiskInput is not None
        assert AssetRiskInput is not None
        assert CorrelationInput is not None
        assert StressScenario is not None
        assert PiotroskiInput is not None

    def test_import_output_models(self):
        """Can import output models from package."""
        from parrot.tools.quant import RiskMetricsOutput, PortfolioRiskOutput
        assert RiskMetricsOutput is not None
        assert PortfolioRiskOutput is not None


# =============================================================================
# EDGE CASES TESTS
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    @pytest.mark.asyncio
    async def test_empty_returns(self, toolkit):
        """Handle empty returns gracefully."""
        result = await toolkit.compute_risk_metrics([])
        # Should return with zeros or handle gracefully
        assert "volatility_annual" in result

    @pytest.mark.asyncio
    async def test_single_return(self, toolkit):
        """Handle single return value."""
        result = await toolkit.compute_risk_metrics([0.01])
        assert "volatility_annual" in result

    @pytest.mark.asyncio
    async def test_correlation_single_asset(self, toolkit):
        """Handle single asset in correlation."""
        np.random.seed(42)
        price_data = {
            "AAPL": list(100 * np.cumprod(1 + np.random.normal(0.001, 0.02, 50))),
        }
        result = await toolkit.compute_correlation_matrix(price_data)
        assert "matrix" in result
        # Single asset correlates 1.0 with itself
        assert result["matrix"]["AAPL"]["AAPL"] == 1.0

    @pytest.mark.asyncio
    async def test_piotroski_minimal_data(self, toolkit):
        """Handle minimal Piotroski data."""
        result = await toolkit.calculate_piotroski_score(
            quarterly_financials={
                "net_income": 1000,
            },
            prior_year_financials=None,
        )
        assert "total_score" in result
        assert "data_completeness_pct" in result
        # Should have low completeness
        assert result["data_completeness_pct"] < 50

    @pytest.mark.asyncio
    async def test_stress_test_empty_portfolio(self, toolkit):
        """Handle empty portfolio in stress test."""
        with pytest.raises(ValueError):
            await toolkit.stress_test_portfolio(
                portfolio_values={},
            )
