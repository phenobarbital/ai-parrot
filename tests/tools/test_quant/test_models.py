"""Unit tests for QuantToolkit Pydantic models."""

import pytest
from parrot.tools.quant.models import (
    PortfolioRiskInput,
    AssetRiskInput,
    CorrelationInput,
    StressScenario,
    PiotroskiInput,
    RiskMetricsOutput,
    PortfolioRiskOutput,
)


class TestPortfolioRiskInput:
    """Tests for PortfolioRiskInput model."""

    def test_valid_input(self):
        """Valid input with weights summing to 1.0."""
        inp = PortfolioRiskInput(
            returns_data={"AAPL": [0.01, 0.02], "SPY": [0.005, 0.01]},
            weights=[0.6, 0.4],
            symbols=["AAPL", "SPY"],
        )
        assert inp.confidence == 0.95  # default
        assert inp.risk_free_rate == 0.04  # default
        assert inp.annualization_factor == 252  # default

    def test_weights_must_sum_to_one(self):
        """Weights not summing to 1.0 raises error."""
        with pytest.raises(ValueError, match="sum to 1.0"):
            PortfolioRiskInput(
                returns_data={"AAPL": [0.01], "SPY": [0.01]},
                weights=[0.5, 0.3],  # sums to 0.8
                symbols=["AAPL", "SPY"],
            )

    def test_weights_sum_tolerance(self):
        """Weights summing to ~1.0 within tolerance are accepted."""
        # Should pass - within 0.01 tolerance
        inp = PortfolioRiskInput(
            returns_data={"AAPL": [0.01], "SPY": [0.01]},
            weights=[0.6, 0.405],  # sums to 1.005
            symbols=["AAPL", "SPY"],
        )
        assert inp is not None

    def test_symbols_weights_length_mismatch(self):
        """Mismatched symbols and weights raises error."""
        with pytest.raises(ValueError, match="same length"):
            PortfolioRiskInput(
                returns_data={"AAPL": [0.01], "SPY": [0.01]},
                weights=[0.6, 0.3, 0.1],
                symbols=["AAPL", "SPY"],
            )

    def test_confidence_bounds_too_high(self):
        """Confidence above 0.99 raises error."""
        with pytest.raises(ValueError):
            PortfolioRiskInput(
                returns_data={"AAPL": [0.01]},
                weights=[1.0],
                symbols=["AAPL"],
                confidence=1.5,
            )

    def test_confidence_bounds_too_low(self):
        """Confidence below 0.01 raises error."""
        with pytest.raises(ValueError):
            PortfolioRiskInput(
                returns_data={"AAPL": [0.01]},
                weights=[1.0],
                symbols=["AAPL"],
                confidence=0.001,
            )

    def test_single_asset_portfolio(self):
        """Single asset portfolio with weight 1.0."""
        inp = PortfolioRiskInput(
            returns_data={"BTC": [0.05, -0.03, 0.02]},
            weights=[1.0],
            symbols=["BTC"],
            annualization_factor=365,  # crypto
        )
        assert inp.annualization_factor == 365

    def test_custom_parameters(self):
        """Custom confidence and risk-free rate."""
        inp = PortfolioRiskInput(
            returns_data={"AAPL": [0.01], "SPY": [0.01]},
            weights=[0.5, 0.5],
            symbols=["AAPL", "SPY"],
            confidence=0.99,
            risk_free_rate=0.05,
        )
        assert inp.confidence == 0.99
        assert inp.risk_free_rate == 0.05


class TestAssetRiskInput:
    """Tests for AssetRiskInput model."""

    def test_defaults(self):
        """Default values are set correctly."""
        inp = AssetRiskInput(returns=[0.01, 0.02, -0.01])
        assert inp.risk_free_rate == 0.04
        assert inp.annualization_factor == 252
        assert inp.benchmark_returns is None

    def test_with_benchmark(self):
        """Input with benchmark returns."""
        inp = AssetRiskInput(
            returns=[0.01, 0.02, -0.01],
            benchmark_returns=[0.005, 0.01, -0.005],
        )
        assert inp.benchmark_returns == [0.005, 0.01, -0.005]

    def test_crypto_annualization(self):
        """Crypto assets use 365-day annualization."""
        inp = AssetRiskInput(
            returns=[0.05, -0.03, 0.02],
            annualization_factor=365,
        )
        assert inp.annualization_factor == 365

    def test_empty_returns(self):
        """Empty returns list is valid (edge case handling in computation)."""
        inp = AssetRiskInput(returns=[])
        assert inp.returns == []


class TestCorrelationInput:
    """Tests for CorrelationInput model."""

    def test_defaults(self):
        """Default values for correlation input."""
        inp = CorrelationInput(
            price_data={"AAPL": [100, 101, 102], "MSFT": [200, 202, 204]}
        )
        assert inp.method == "pearson"
        assert inp.returns_based is True

    def test_spearman_method(self):
        """Spearman correlation method."""
        inp = CorrelationInput(
            price_data={"AAPL": [100, 101], "MSFT": [200, 202]},
            method="spearman",
        )
        assert inp.method == "spearman"

    def test_kendall_method(self):
        """Kendall correlation method."""
        inp = CorrelationInput(
            price_data={"AAPL": [100, 101], "MSFT": [200, 202]},
            method="kendall",
        )
        assert inp.method == "kendall"

    def test_price_based_correlation(self):
        """Disable returns-based correlation (not recommended but allowed)."""
        inp = CorrelationInput(
            price_data={"AAPL": [100, 101], "MSFT": [200, 202]},
            returns_based=False,
        )
        assert inp.returns_based is False

    def test_invalid_method_rejected(self):
        """Invalid correlation method raises error."""
        with pytest.raises(ValueError):
            CorrelationInput(
                price_data={"AAPL": [100, 101]},
                method="invalid_method",  # type: ignore
            )


class TestStressScenario:
    """Tests for StressScenario model."""

    def test_scenario_creation(self):
        """Stress scenario with shocks."""
        scenario = StressScenario(
            name="covid_crash",
            asset_shocks={"SPY": -0.34, "BTC": -0.50},
        )
        assert scenario.name == "covid_crash"
        assert scenario.asset_shocks["SPY"] == -0.34
        assert scenario.asset_shocks["BTC"] == -0.50

    def test_positive_shocks(self):
        """Scenario with positive shocks (e.g., bonds during crash)."""
        scenario = StressScenario(
            name="flight_to_safety",
            asset_shocks={"TLT": 0.20, "GLD": 0.10},
        )
        assert scenario.asset_shocks["TLT"] == 0.20

    def test_mixed_shocks(self):
        """Scenario with both positive and negative shocks."""
        scenario = StressScenario(
            name="rate_hike",
            asset_shocks={"SPY": -0.10, "TLT": -0.15, "GLD": 0.05},
        )
        assert len(scenario.asset_shocks) == 3

    def test_empty_shocks(self):
        """Scenario with no shocks (edge case)."""
        scenario = StressScenario(
            name="no_change",
            asset_shocks={},
        )
        assert scenario.asset_shocks == {}


class TestPiotroskiInput:
    """Tests for PiotroskiInput model."""

    def test_minimal_input(self):
        """Minimal input with only quarterly financials."""
        inp = PiotroskiInput(
            quarterly_financials={
                "net_income": 1000000,
                "total_assets": 10000000,
            }
        )
        assert inp.quarterly_financials["net_income"] == 1000000
        assert inp.prior_year_financials == {}

    def test_full_input(self):
        """Full input with both quarters."""
        inp = PiotroskiInput(
            quarterly_financials={
                "net_income": 15_000_000,
                "total_assets": 100_000_000,
                "operating_cash_flow": 18_000_000,
                "current_assets": 40_000_000,
                "current_liabilities": 20_000_000,
                "long_term_debt": 25_000_000,
                "shares_outstanding": 10_000_000,
                "revenue": 80_000_000,
                "gross_profit": 32_000_000,
            },
            prior_year_financials={
                "total_assets": 95_000_000,
                "current_ratio": 1.8,
                "long_term_debt": 28_000_000,
                "shares_outstanding": 10_000_000,
                "asset_turnover": 0.75,
                "gross_margin": 0.38,
            },
        )
        assert inp.quarterly_financials["net_income"] == 15_000_000
        assert inp.prior_year_financials["current_ratio"] == 1.8

    def test_negative_values(self):
        """Negative values are valid (e.g., net loss)."""
        inp = PiotroskiInput(
            quarterly_financials={
                "net_income": -5_000_000,  # Loss
                "total_assets": 50_000_000,
            }
        )
        assert inp.quarterly_financials["net_income"] == -5_000_000


class TestRiskMetricsOutput:
    """Tests for RiskMetricsOutput model."""

    def test_output_fields(self):
        """Output model has all required fields."""
        out = RiskMetricsOutput(
            volatility_annual=0.25,
            beta=1.2,
            sharpe_ratio=1.5,
            max_drawdown=-0.15,
            var_95=-0.02,
            var_99=-0.03,
            cvar_95=-0.025,
        )
        assert out.volatility_annual == 0.25
        assert out.beta == 1.2
        assert out.sharpe_ratio == 1.5
        assert out.max_drawdown == -0.15
        assert out.var_95 == -0.02
        assert out.var_99 == -0.03
        assert out.cvar_95 == -0.025

    def test_optional_beta(self):
        """Beta can be None when no benchmark provided."""
        out = RiskMetricsOutput(
            volatility_annual=0.30,
            beta=None,
            sharpe_ratio=0.8,
            max_drawdown=-0.20,
            var_95=-0.025,
            var_99=-0.035,
            cvar_95=-0.030,
        )
        assert out.beta is None


class TestPortfolioRiskOutput:
    """Tests for PortfolioRiskOutput model."""

    def test_all_fields(self):
        """All portfolio risk output fields."""
        out = PortfolioRiskOutput(
            var_1d_95_pct=-0.02,
            var_1d_99_pct=-0.03,
            cvar_1d_95_pct=-0.025,
            portfolio_volatility=0.18,
            portfolio_beta=0.95,
            portfolio_sharpe=1.2,
            max_drawdown=-0.12,
            net_exposure=1.0,
            gross_exposure=1.0,
        )
        assert out.var_1d_95_pct == -0.02
        assert out.portfolio_volatility == 0.18
        assert out.net_exposure == 1.0

    def test_optional_beta(self):
        """Portfolio beta can be None."""
        out = PortfolioRiskOutput(
            var_1d_95_pct=-0.02,
            var_1d_99_pct=-0.03,
            cvar_1d_95_pct=-0.025,
            portfolio_volatility=0.20,
            portfolio_beta=None,
            portfolio_sharpe=0.9,
            max_drawdown=-0.15,
            net_exposure=0.8,
            gross_exposure=1.2,
        )
        assert out.portfolio_beta is None

    def test_short_positions(self):
        """Portfolio with short positions (net < gross)."""
        out = PortfolioRiskOutput(
            var_1d_95_pct=-0.03,
            var_1d_99_pct=-0.04,
            cvar_1d_95_pct=-0.035,
            portfolio_volatility=0.25,
            portfolio_beta=1.1,
            portfolio_sharpe=0.7,
            max_drawdown=-0.20,
            net_exposure=0.6,  # 80% long - 20% short
            gross_exposure=1.0,  # 80% + 20%
        )
        assert out.net_exposure < out.gross_exposure


class TestModelImports:
    """Tests for package imports."""

    def test_import_from_package(self):
        """Can import models from parrot.tools.quant."""
        from parrot.tools.quant import (
            PortfolioRiskInput,
            AssetRiskInput,
            CorrelationInput,
            StressScenario,
            PiotroskiInput,
            RiskMetricsOutput,
            PortfolioRiskOutput,
        )

        assert PortfolioRiskInput is not None
        assert AssetRiskInput is not None
        assert CorrelationInput is not None
        assert StressScenario is not None
        assert PiotroskiInput is not None
        assert RiskMetricsOutput is not None
        assert PortfolioRiskOutput is not None

    def test_import_from_models_module(self):
        """Can import directly from models module."""
        from parrot.tools.quant.models import PortfolioRiskInput

        assert PortfolioRiskInput is not None
