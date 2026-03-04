"""Unit tests for QuantToolkit Risk Metrics Engine."""

import pytest
import numpy as np
import pandas as pd
from parrot.tools.quant.risk_metrics import (
    compute_returns,
    compute_var_parametric,
    compute_var_historical,
    compute_cvar,
    compute_max_drawdown,
    compute_beta,
    compute_sharpe_ratio,
    compute_volatility_annual,
    compute_portfolio_var_parametric,
    compute_portfolio_var_historical,
    compute_portfolio_cvar,
    compute_rolling_metrics,
    compute_single_asset_risk,
    compute_portfolio_risk,
    compute_exposure,
)
from parrot.tools.quant.models import AssetRiskInput, PortfolioRiskInput


@pytest.fixture
def sample_returns():
    """60 days of simulated returns."""
    np.random.seed(42)
    return np.random.normal(0.001, 0.02, 60)


@pytest.fixture
def sample_benchmark_returns():
    """60 days of benchmark returns."""
    np.random.seed(123)
    return np.random.normal(0.0008, 0.015, 60)


@pytest.fixture
def sample_prices():
    """Sample price series."""
    return [100.0, 102.0, 101.0, 103.0, 105.0, 104.0, 106.0]


# =============================================================================
# RETURNS COMPUTATION
# =============================================================================


class TestComputeReturns:
    """Tests for compute_returns function."""

    def test_basic_returns(self, sample_prices):
        """Compute returns from price series."""
        returns = compute_returns(sample_prices)
        assert len(returns) == len(sample_prices) - 1
        # First return: (102 - 100) / 100 = 0.02
        assert abs(returns[0] - 0.02) < 0.0001

    def test_empty_prices(self):
        """Empty prices returns empty array."""
        returns = compute_returns([])
        assert len(returns) == 0

    def test_single_price(self):
        """Single price returns empty array."""
        returns = compute_returns([100.0])
        assert len(returns) == 0


# =============================================================================
# VALUE AT RISK (VaR)
# =============================================================================


class TestVaR:
    """Tests for VaR calculations."""

    def test_var_parametric_95(self, sample_returns):
        """VaR at 95% confidence."""
        var = compute_var_parametric(sample_returns, 0.95)
        assert var < 0  # Should be a loss
        assert -0.10 < var < 0  # Reasonable range

    def test_var_parametric_99(self, sample_returns):
        """VaR at 99% confidence."""
        var = compute_var_parametric(sample_returns, 0.99)
        assert var < 0

    def test_var_99_more_conservative(self, sample_returns):
        """VaR at 99% should be more negative than 95%."""
        var_95 = compute_var_parametric(sample_returns, 0.95)
        var_99 = compute_var_parametric(sample_returns, 0.99)
        assert var_99 < var_95  # More conservative (more negative)

    def test_var_empty_returns(self):
        """VaR with empty returns returns 0."""
        var = compute_var_parametric(np.array([]), 0.95)
        assert var == 0.0

    def test_var_zero_variance(self):
        """VaR with zero variance returns 0."""
        constant_returns = np.array([0.01, 0.01, 0.01, 0.01])
        var = compute_var_parametric(constant_returns, 0.95)
        # Zero std means VaR calculation returns 0
        assert var == 0.0

    def test_var_historical(self, sample_returns):
        """Historical VaR calculation."""
        var = compute_var_historical(sample_returns, 0.95)
        assert var < 0
        # Should be near the 5th percentile of returns
        expected = np.percentile(sample_returns, 5)
        assert abs(var - expected) < 0.0001

    def test_var_historical_empty(self):
        """Historical VaR with empty returns."""
        var = compute_var_historical(np.array([]), 0.95)
        assert var == 0.0


# =============================================================================
# CONDITIONAL VaR (CVaR)
# =============================================================================


class TestCVaR:
    """Tests for CVaR calculations."""

    def test_cvar_greater_than_var(self, sample_returns):
        """CVaR (Expected Shortfall) is more negative than VaR."""
        var = compute_var_parametric(sample_returns, 0.95)
        cvar = compute_cvar(sample_returns, 0.95)
        # Both negative, CVaR should be more negative (more conservative)
        assert cvar <= var

    def test_cvar_empty_returns(self):
        """CVaR with empty returns."""
        cvar = compute_cvar(np.array([]), 0.95)
        assert cvar == 0.0

    def test_cvar_99(self, sample_returns):
        """CVaR at 99% confidence."""
        cvar = compute_cvar(sample_returns, 0.99)
        assert cvar < 0


# =============================================================================
# MAXIMUM DRAWDOWN
# =============================================================================


class TestMaxDrawdown:
    """Tests for max drawdown calculations."""

    def test_max_drawdown_known_series(self):
        """Max drawdown on a known series."""
        # Price: 100 -> 120 -> 90 -> 100
        # Returns: +20%, -25%, +11.1%
        returns = np.array([0.20, -0.25, 0.111])
        dd = compute_max_drawdown(returns)
        # After +20%: value=1.2, max=1.2, dd=0
        # After -25%: value=0.9, max=1.2, dd=-0.25
        assert abs(dd - (-0.25)) < 0.01

    def test_max_drawdown_no_drawdown(self):
        """No drawdown when all returns positive."""
        returns = np.array([0.01, 0.02, 0.01, 0.03])
        dd = compute_max_drawdown(returns)
        assert dd == 0.0

    def test_max_drawdown_empty(self):
        """Empty returns returns 0."""
        dd = compute_max_drawdown(np.array([]))
        assert dd == 0.0

    def test_max_drawdown_single_negative(self):
        """Single negative return."""
        returns = np.array([-0.10])
        dd = compute_max_drawdown(returns)
        # After -10%: value=0.9, max=0.9, dd=0 (starts from this point)
        assert dd == 0.0


# =============================================================================
# BETA
# =============================================================================


class TestBeta:
    """Tests for beta calculations."""

    def test_beta_calculation(self, sample_returns, sample_benchmark_returns):
        """Beta calculation matches manual."""
        beta = compute_beta(sample_returns, sample_benchmark_returns)
        # Manual verification
        cov = np.cov(sample_returns, sample_benchmark_returns)[0, 1]
        var_bench = np.var(sample_benchmark_returns, ddof=1)
        expected = cov / var_bench
        assert abs(beta - expected) < 0.001

    def test_beta_zero_variance(self):
        """Beta is 0 when benchmark has zero variance."""
        asset = np.array([0.01, 0.02, -0.01])
        benchmark = np.array([0.0, 0.0, 0.0])
        beta = compute_beta(asset, benchmark)
        assert beta == 0.0

    def test_beta_length_mismatch(self):
        """Beta raises error on length mismatch."""
        asset = np.array([0.01, 0.02, -0.01])
        benchmark = np.array([0.01, 0.02])
        with pytest.raises(ValueError, match="same length"):
            compute_beta(asset, benchmark)

    def test_beta_empty_returns(self):
        """Empty returns returns 0."""
        beta = compute_beta(np.array([]), np.array([]))
        assert beta == 0.0

    def test_beta_perfect_correlation(self):
        """Beta is 1 when asset equals benchmark."""
        returns = np.array([0.01, 0.02, -0.01, 0.015])
        beta = compute_beta(returns, returns)
        assert abs(beta - 1.0) < 0.001


# =============================================================================
# SHARPE RATIO
# =============================================================================


class TestSharpe:
    """Tests for Sharpe ratio calculations."""

    def test_sharpe_ratio(self, sample_returns):
        """Sharpe ratio calculation."""
        sharpe = compute_sharpe_ratio(sample_returns, risk_free_rate=0.04)
        assert isinstance(sharpe, float)

    def test_sharpe_zero_volatility(self):
        """Sharpe is 0 when volatility is zero."""
        constant_returns = np.array([0.001, 0.001, 0.001])
        sharpe = compute_sharpe_ratio(constant_returns)
        assert sharpe == 0.0

    def test_sharpe_empty_returns(self):
        """Empty returns returns 0."""
        sharpe = compute_sharpe_ratio(np.array([]))
        assert sharpe == 0.0

    def test_sharpe_different_annualization(self, sample_returns):
        """Sharpe with crypto annualization (365 days)."""
        sharpe_stocks = compute_sharpe_ratio(
            sample_returns, annualization_factor=252
        )
        sharpe_crypto = compute_sharpe_ratio(
            sample_returns, annualization_factor=365
        )
        # Crypto annualization should give different result
        assert sharpe_stocks != sharpe_crypto


# =============================================================================
# VOLATILITY
# =============================================================================


class TestVolatility:
    """Tests for volatility calculations."""

    def test_volatility_annual(self, sample_returns):
        """Annualized volatility calculation."""
        vol = compute_volatility_annual(sample_returns, annualization_factor=252)
        # Should be roughly sample_std * sqrt(252)
        daily_std = np.std(sample_returns, ddof=1)
        expected = daily_std * np.sqrt(252)
        assert abs(vol - expected) < 0.0001

    def test_volatility_empty(self):
        """Empty returns returns 0."""
        vol = compute_volatility_annual(np.array([]))
        assert vol == 0.0


# =============================================================================
# PORTFOLIO VAR
# =============================================================================


class TestPortfolioVaR:
    """Tests for portfolio VaR calculations."""

    @pytest.fixture
    def portfolio_returns_df(self):
        """Portfolio returns DataFrame."""
        np.random.seed(42)
        return pd.DataFrame({
            "AAPL": np.random.normal(0.001, 0.02, 60),
            "SPY": np.random.normal(0.0008, 0.015, 60),
        })

    @pytest.fixture
    def portfolio_weights(self):
        """Portfolio weights."""
        return np.array([0.6, 0.4])

    def test_portfolio_var_parametric(self, portfolio_returns_df, portfolio_weights):
        """Portfolio VaR with covariance method."""
        var = compute_portfolio_var_parametric(
            portfolio_returns_df, portfolio_weights, 0.95
        )
        assert var < 0

    def test_portfolio_var_historical(self, portfolio_returns_df, portfolio_weights):
        """Portfolio VaR with historical simulation."""
        var = compute_portfolio_var_historical(
            portfolio_returns_df, portfolio_weights, 0.95
        )
        assert var < 0

    def test_portfolio_var_empty(self):
        """Empty portfolio returns 0."""
        var = compute_portfolio_var_parametric(pd.DataFrame(), np.array([]))
        assert var == 0.0

    def test_portfolio_cvar(self, portfolio_returns_df, portfolio_weights):
        """Portfolio CVaR calculation."""
        cvar = compute_portfolio_cvar(portfolio_returns_df, portfolio_weights, 0.95)
        var = compute_portfolio_var_parametric(
            portfolio_returns_df, portfolio_weights, 0.95
        )
        # CVaR should be more conservative (more negative)
        assert cvar <= var


# =============================================================================
# ROLLING METRICS
# =============================================================================


class TestRollingMetrics:
    """Tests for rolling metrics calculations."""

    def test_rolling_window_length(self, sample_returns):
        """Rolling metrics produce correct output length."""
        result = compute_rolling_metrics(sample_returns, window=20)
        # With 60 samples and window=20, should have 41 points
        assert len(result["rolling_vol"]) == 41
        assert len(result["rolling_sharpe"]) == 41
        assert len(result["rolling_var_95"]) == 41

    def test_rolling_with_benchmark(self, sample_returns, sample_benchmark_returns):
        """Rolling metrics with benchmark for beta."""
        result = compute_rolling_metrics(
            sample_returns,
            window=20,
            benchmark_returns=sample_benchmark_returns,
        )
        assert len(result["rolling_beta"]) == 41
        # Beta should be computed
        assert not np.all(result["rolling_beta"] == 0)

    def test_rolling_insufficient_data(self):
        """Rolling with insufficient data returns empty."""
        short_returns = np.array([0.01, 0.02, 0.03])
        result = compute_rolling_metrics(short_returns, window=20)
        assert len(result["rolling_vol"]) == 0

    def test_rolling_exact_window(self, sample_returns):
        """Rolling with exact window size."""
        result = compute_rolling_metrics(sample_returns[:20], window=20)
        assert len(result["rolling_vol"]) == 1


# =============================================================================
# HIGH-LEVEL WRAPPERS
# =============================================================================


class TestSingleAssetRisk:
    """Tests for compute_single_asset_risk wrapper."""

    def test_basic_calculation(self, sample_returns):
        """Basic single asset risk calculation."""
        inp = AssetRiskInput(returns=sample_returns.tolist())
        result = compute_single_asset_risk(inp)

        assert result.volatility_annual > 0
        assert result.sharpe_ratio is not None
        assert result.max_drawdown <= 0
        assert result.var_95 < 0
        assert result.var_99 < result.var_95  # More conservative
        assert result.cvar_95 <= result.var_95  # More conservative
        assert result.beta is None  # No benchmark provided

    def test_with_benchmark(self, sample_returns, sample_benchmark_returns):
        """Single asset risk with benchmark."""
        inp = AssetRiskInput(
            returns=sample_returns.tolist(),
            benchmark_returns=sample_benchmark_returns.tolist(),
        )
        result = compute_single_asset_risk(inp)

        assert result.beta is not None
        assert isinstance(result.beta, float)


class TestPortfolioRisk:
    """Tests for compute_portfolio_risk wrapper."""

    def test_basic_calculation(self):
        """Basic portfolio risk calculation."""
        np.random.seed(42)
        inp = PortfolioRiskInput(
            returns_data={
                "AAPL": np.random.normal(0.001, 0.02, 60).tolist(),
                "SPY": np.random.normal(0.0008, 0.015, 60).tolist(),
            },
            weights=[0.6, 0.4],
            symbols=["AAPL", "SPY"],
        )
        result = compute_portfolio_risk(inp)

        assert result.var_1d_95_pct < 0
        assert result.var_1d_99_pct < result.var_1d_95_pct
        assert result.cvar_1d_95_pct <= result.var_1d_95_pct
        assert result.portfolio_volatility > 0
        assert result.max_drawdown <= 0
        assert result.net_exposure == 1.0
        assert result.gross_exposure == 1.0

    def test_short_positions(self):
        """Portfolio with short positions."""
        np.random.seed(42)
        inp = PortfolioRiskInput(
            returns_data={
                "AAPL": np.random.normal(0.001, 0.02, 60).tolist(),
                "SPY": np.random.normal(0.0008, 0.015, 60).tolist(),
            },
            weights=[1.2, -0.2],  # Long/short
            symbols=["AAPL", "SPY"],
        )
        result = compute_portfolio_risk(inp)

        assert result.net_exposure == 1.0  # 1.2 - 0.2
        assert result.gross_exposure == 1.4  # 1.2 + 0.2


class TestExposure:
    """Tests for exposure calculations."""

    def test_long_only(self):
        """Long-only portfolio exposure."""
        result = compute_exposure([0.6, 0.4])
        assert result["net_exposure"] == 1.0
        assert result["gross_exposure"] == 1.0

    def test_long_short(self):
        """Long/short portfolio exposure."""
        result = compute_exposure([0.8, -0.2])
        assert abs(result["net_exposure"] - 0.6) < 0.001
        assert abs(result["gross_exposure"] - 1.0) < 0.001

    def test_leveraged(self):
        """Leveraged portfolio exposure."""
        result = compute_exposure([1.5, 0.5])
        assert result["net_exposure"] == 2.0
        assert result["gross_exposure"] == 2.0


# =============================================================================
# CVaR >= VaR INVARIANT
# =============================================================================


class TestCVaRVaRInvariant:
    """Tests ensuring CVaR is always more conservative than VaR."""

    def test_invariant_single_asset(self, sample_returns):
        """CVaR >= VaR for single asset (both negative, CVaR more negative)."""
        for confidence in [0.90, 0.95, 0.99]:
            var = compute_var_parametric(sample_returns, confidence)
            cvar = compute_cvar(sample_returns, confidence)
            assert cvar <= var, f"CVaR ({cvar}) should be <= VaR ({var}) at {confidence}"

    def test_invariant_portfolio(self):
        """CVaR >= VaR for portfolio."""
        np.random.seed(42)
        returns_df = pd.DataFrame({
            "A": np.random.normal(0.001, 0.02, 100),
            "B": np.random.normal(0.0008, 0.015, 100),
        })
        weights = np.array([0.5, 0.5])

        var = compute_portfolio_var_parametric(returns_df, weights, 0.95)
        cvar = compute_portfolio_cvar(returns_df, weights, 0.95)
        assert cvar <= var


# =============================================================================
# EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_all_zero_returns(self):
        """All zero returns."""
        returns = np.zeros(60)
        var = compute_var_parametric(returns, 0.95)
        cvar = compute_cvar(returns, 0.95)
        vol = compute_volatility_annual(returns)
        sharpe = compute_sharpe_ratio(returns)

        assert var == 0.0
        assert cvar == 0.0
        assert vol == 0.0
        assert sharpe == 0.0

    def test_single_return(self):
        """Single return value."""
        returns = np.array([0.01])
        # Should not crash - single sample has undefined std with ddof=1
        vol = compute_volatility_annual(returns)
        # Result may be nan for single sample, just ensure no crash
        assert vol is not None

    def test_negative_risk_free_rate(self, sample_returns):
        """Negative risk-free rate (like some countries)."""
        sharpe = compute_sharpe_ratio(sample_returns, risk_free_rate=-0.01)
        assert isinstance(sharpe, float)

    def test_high_leverage(self):
        """High leverage portfolio."""
        np.random.seed(42)
        inp = PortfolioRiskInput(
            returns_data={
                "A": np.random.normal(0.001, 0.02, 60).tolist(),
                "B": np.random.normal(0.0008, 0.015, 60).tolist(),
            },
            weights=[2.0, -1.0],  # 2x long, 1x short
            symbols=["A", "B"],
        )
        result = compute_portfolio_risk(inp)
        assert result.gross_exposure == 3.0
        assert result.net_exposure == 1.0
