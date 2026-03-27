"""Integration tests for QuantToolkit.

These tests verify end-to-end workflows simulating how agents
(risk analyst, equity analyst, sentiment analyst) use the toolkit.
They also verify output compatibility with the finance deliberation schemas.
"""

import numpy as np
import pytest

from parrot.tools.quant import QuantToolkit


@pytest.fixture
def toolkit():
    """Instantiate a fresh QuantToolkit."""
    return QuantToolkit()


# ─────────────────────────────────────────────────────────────────────────────
# Risk Analyst Workflow
# ─────────────────────────────────────────────────────────────────────────────


class TestRiskAnalystWorkflow:
    """Tests simulating the risk analyst agent workflow."""

    @pytest.mark.asyncio
    async def test_full_risk_analysis(
        self, toolkit, realistic_equity_prices, sample_portfolio
    ):
        """Risk analyst: portfolio risk → correlation regime → stress test."""
        returns = realistic_equity_prices["returns"]

        # Step 1: Portfolio risk for equities in the portfolio
        portfolio_returns = {
            k: v for k, v in returns.items() if k in sample_portfolio
        }
        total_value = sum(
            v for k, v in sample_portfolio.items() if k in portfolio_returns
        )
        weights = [
            sample_portfolio[s] / total_value
            for s in portfolio_returns
        ]

        risk_metrics = await toolkit.compute_portfolio_risk(
            returns_data=portfolio_returns,
            weights=weights,
            symbols=list(portfolio_returns.keys()),
        )

        assert "portfolio_volatility" in risk_metrics
        assert isinstance(risk_metrics["portfolio_volatility"], float)
        assert risk_metrics["portfolio_volatility"] > 0

        # Step 2: Correlation regime detection
        regime = await toolkit.detect_correlation_regimes(
            price_data=realistic_equity_prices["prices"],
            short_window=20,
            long_window=60,
        )

        assert "regime_alerts" in regime
        assert isinstance(regime["regime_alerts"], list)

        # Step 3: Stress test
        stress = await toolkit.stress_test_portfolio(
            portfolio_values=sample_portfolio,
            scenario_names=["covid_crash_2020", "rate_hike_shock"],
        )

        assert "worst_scenario" in stress
        assert "max_loss_pct" in stress
        assert stress["max_loss_pct"] < 0  # should be a loss

    @pytest.mark.asyncio
    async def test_risk_summary_for_analyst_report(
        self, toolkit, realistic_equity_prices
    ):
        """Verify output can populate AnalystReport.portfolio_risk_summary."""
        returns = realistic_equity_prices["returns"]
        prices = realistic_equity_prices["prices"]

        # Compute portfolio risk
        risk = await toolkit.compute_portfolio_risk(
            returns_data=returns,
            weights=[0.4, 0.35, 0.25],
            symbols=["AAPL", "MSFT", "SPY"],
        )

        # Compute correlation
        corr = await toolkit.compute_correlation_matrix(prices)

        # Build risk summary
        risk_summary = {
            "var_1d_95_pct": risk["var_1d_95_pct"],
            "portfolio_volatility": risk["portfolio_volatility"],
            "max_drawdown": risk["max_drawdown"],
        }

        # Find the top correlation pair
        matrix = corr["matrix"]
        max_corr = 0.0
        top_pair = None
        symbols = list(matrix.keys())
        for i, s1 in enumerate(symbols):
            for s2 in symbols[i + 1:]:
                c = abs(matrix[s1][s2])
                if c > max_corr:
                    max_corr = c
                    top_pair = f"{s1}-{s2}"

        risk_summary["top_correlation_pair"] = top_pair
        risk_summary["top_correlation"] = max_corr

        assert all(
            k in risk_summary
            for k in ["var_1d_95_pct", "portfolio_volatility", "top_correlation_pair"]
        )
        assert risk_summary["var_1d_95_pct"] < 0  # VaR is a loss
        assert top_pair is not None


# ─────────────────────────────────────────────────────────────────────────────
# Equity Analyst Workflow
# ─────────────────────────────────────────────────────────────────────────────


class TestEquityAnalystWorkflow:
    """Tests simulating the equity analyst agent workflow."""

    @pytest.mark.asyncio
    async def test_piotroski_screening(self, toolkit, sample_financials):
        """Equity analyst: batch Piotroski scoring and ranking."""
        results = await toolkit.batch_piotroski_scores(sample_financials)

        assert "AAPL" in results
        assert "MSFT" in results

        ranked = sorted(
            results.items(),
            key=lambda x: x[1]["total_score"],
            reverse=True,
        )

        for _symbol, data in ranked:
            assert 0 <= data["total_score"] <= 9
            assert data["interpretation"] in [
                "Excellent", "Good", "Fair", "Poor"
            ]

    @pytest.mark.asyncio
    async def test_piotroski_for_data_points(self, toolkit, sample_financials):
        """Verify Piotroski output populates AnalystReport.data_points."""
        result = await toolkit.calculate_piotroski_score(
            quarterly_financials=sample_financials["AAPL"]["quarterly_financials"],
            prior_year_financials=sample_financials["AAPL"]["prior_year_financials"],
        )

        data_point = (
            f"Piotroski F-Score: {result['total_score']}/9 "
            f"({result['interpretation']}), "
            f"Profitability: {result['category_scores']['profitability']}/4, "
            f"Leverage: {result['category_scores']['leverage_liquidity']}/3, "
            f"Efficiency: {result['category_scores']['operating_efficiency']}/2"
        )

        assert "Piotroski F-Score:" in data_point
        assert result["interpretation"] in data_point
        assert "category_scores" in result


# ─────────────────────────────────────────────────────────────────────────────
# Sentiment Analyst Workflow
# ─────────────────────────────────────────────────────────────────────────────


class TestSentimentAnalystWorkflow:
    """Tests simulating the sentiment analyst workflow."""

    @pytest.mark.asyncio
    async def test_volatility_analysis(self, toolkit, realistic_equity_prices):
        """Sentiment analyst: volatility cone with percentile interpretation."""
        returns = realistic_equity_prices["returns"]["SPY"]

        cone = await toolkit.compute_volatility_cone(returns)

        assert isinstance(cone, dict)
        assert len(cone) > 0

        for window, data in cone.items():
            assert "percentile" in data
            assert "current" in data
            assert "min" in data
            assert "max" in data
            assert "median" in data
            assert 0 <= data["percentile"] <= 100

            # Classify regime
            if data["percentile"] > 90:
                vol_regime = "elevated"
            elif data["percentile"] < 10:
                vol_regime = "depressed"
            else:
                vol_regime = "normal"
            assert vol_regime in ["elevated", "depressed", "normal"]

    @pytest.mark.asyncio
    async def test_iv_rv_analysis(self, toolkit, realistic_equity_prices):
        """IV vs RV spread analysis for options sentiment."""
        returns = realistic_equity_prices["returns"]["SPY"]

        rv_series = await toolkit.compute_realized_volatility(
            returns=returns,
            window=20,
        )

        implied_vol = 0.25  # 25% annualized IV

        spread = await toolkit.compute_iv_rv_spread(
            implied_vol=implied_vol,
            realized_vol_series=rv_series,
        )

        assert "regime" in spread
        assert spread["regime"] in ["fear_premium", "complacent", "normal"]
        assert "implied_vol" in spread
        assert "realized_vol" in spread
        assert "spread" in spread
        assert "spread_pct" in spread


# ─────────────────────────────────────────────────────────────────────────────
# Cross-Asset Correlation
# ─────────────────────────────────────────────────────────────────────────────


class TestCrossAssetCorrelation:
    """Tests for cross-asset correlation between equities and crypto."""

    @pytest.mark.asyncio
    async def test_equity_crypto_correlation(
        self, toolkit, realistic_equity_prices, realistic_crypto_prices
    ):
        """Cross-asset correlation with calendar alignment."""
        result = await toolkit.compute_cross_asset_correlation(
            equity_prices=realistic_equity_prices["prices"],
            crypto_prices=realistic_crypto_prices["prices"],
            timestamps_equity=realistic_equity_prices["dates"],
            timestamps_crypto=realistic_crypto_prices["dates"],
        )

        assert "cross_asset_correlations" in result
        assert result["common_dates_count"] > 0

        cross = result["cross_asset_correlations"]
        assert any("BTC" in k for k in cross)


# ─────────────────────────────────────────────────────────────────────────────
# Schema Compatibility
# ─────────────────────────────────────────────────────────────────────────────


class TestSchemaCompatibility:
    """Verify output compatibility with finance deliberation schemas."""

    @pytest.mark.asyncio
    async def test_portfolio_snapshot_compatibility(
        self, toolkit, realistic_equity_prices
    ):
        """Output can populate PortfolioSnapshot.max_drawdown_pct."""
        returns = realistic_equity_prices["returns"]

        risk = await toolkit.compute_portfolio_risk(
            returns_data=returns,
            weights=[0.4, 0.35, 0.25],
            symbols=list(returns.keys()),
        )

        max_dd = risk.get("max_drawdown")
        assert max_dd is not None
        assert isinstance(max_dd, float)
        assert max_dd <= 0  # drawdown is negative

    @pytest.mark.asyncio
    async def test_analyst_report_key_risks(
        self, toolkit, realistic_equity_prices
    ):
        """Correlation regime alerts can populate AnalystReport.key_risks."""
        regime = await toolkit.detect_correlation_regimes(
            price_data=realistic_equity_prices["prices"],
            short_window=20,
            long_window=60,
            z_threshold=1.5,  # lower to get alerts with synthetic data
        )

        key_risks = []
        for alert in regime["regime_alerts"]:
            risk = (
                f"Correlation {alert['alert']}: {alert['pair']} "
                f"(short={alert['short_corr']:.2f}, "
                f"long={alert['long_corr']:.2f}, "
                f"z={alert['z_score']:.1f})"
            )
            key_risks.append(risk)

        assert all(isinstance(r, str) for r in key_risks)


# ─────────────────────────────────────────────────────────────────────────────
# Edge Cases
# ─────────────────────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_single_asset_portfolio(self, toolkit):
        """Portfolio with only one asset."""
        np.random.seed(42)
        returns = list(np.random.normal(0.001, 0.02, 60))

        result = await toolkit.compute_portfolio_risk(
            returns_data={"AAPL": returns},
            weights=[1.0],
            symbols=["AAPL"],
        )

        assert "portfolio_volatility" in result
        assert result["portfolio_volatility"] > 0

    @pytest.mark.asyncio
    async def test_stress_test_unknown_symbols(self, toolkit):
        """Stress test with symbols not in the predefined scenario."""
        portfolio = {"UNKNOWN_TICKER": 100000}

        result = await toolkit.stress_test_portfolio(
            portfolio_values=portfolio,
            scenario_names=["covid_crash_2020"],
        )

        impacts = result["scenario_results"]["covid_crash_2020"]["position_impacts"]
        assert impacts["UNKNOWN_TICKER"]["shock"] == 0

    @pytest.mark.asyncio
    async def test_stress_test_all_predefined_scenarios(self, toolkit, sample_portfolio):
        """Stress test using all predefined scenarios at once."""
        result = await toolkit.stress_test_portfolio(
            portfolio_values=sample_portfolio,
        )

        assert "scenario_results" in result
        assert len(result["scenario_results"]) > 0
        assert "worst_scenario" in result
        assert result["worst_scenario"] is not None

    @pytest.mark.asyncio
    async def test_rolling_metrics_workflow(self, toolkit, realistic_equity_prices):
        """Rolling risk metrics for regime detection."""
        returns = realistic_equity_prices["returns"]["SPY"]

        rolling = await toolkit.compute_rolling_metrics(
            returns=returns,
            window=60,
        )

        assert "rolling_vol" in rolling
        assert "rolling_sharpe" in rolling
        assert "rolling_var_95" in rolling
        assert len(rolling["rolling_vol"]) > 0
