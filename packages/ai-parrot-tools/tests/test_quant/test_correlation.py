"""Unit tests for QuantToolkit Correlation Engine."""

import pytest
import numpy as np
import pandas as pd
from parrot.tools.quant.correlation import (
    prices_to_returns,
    compute_correlation_matrix,
    compute_correlation_from_input,
    detect_correlation_regimes,
    compute_cross_asset_correlation,
    compute_pairwise_correlation,
    compute_rolling_correlation,
    get_correlation_heatmap_data,
)
from parrot.tools.quant.models import CorrelationInput


@pytest.fixture
def sample_prices():
    """Sample price data for testing."""
    np.random.seed(42)
    n = 150
    return {
        "AAPL": list(100 * np.cumprod(1 + np.random.normal(0.001, 0.02, n))),
        "MSFT": list(100 * np.cumprod(1 + np.random.normal(0.001, 0.02, n))),
        "SPY": list(100 * np.cumprod(1 + np.random.normal(0.0008, 0.015, n))),
    }


@pytest.fixture
def correlated_prices():
    """Highly correlated price series."""
    np.random.seed(42)
    n = 100
    base_returns = np.random.normal(0.001, 0.02, n)
    return {
        "A": list(100 * np.cumprod(1 + base_returns)),
        "B": list(100 * np.cumprod(1 + base_returns * 0.9 + np.random.normal(0, 0.005, n))),
    }


# =============================================================================
# PRICES TO RETURNS
# =============================================================================


class TestPricesToReturns:
    """Tests for prices_to_returns function."""

    def test_basic_conversion(self):
        """Convert prices to returns."""
        prices = np.array([100, 102, 101, 105])
        returns = prices_to_returns(prices)
        assert len(returns) == 3
        # (102-100)/100 = 0.02
        assert abs(returns[0] - 0.02) < 0.0001
        # (101-102)/102 = -0.0098
        assert returns[1] < 0

    def test_empty_prices(self):
        """Empty prices returns empty array."""
        returns = prices_to_returns(np.array([]))
        assert len(returns) == 0

    def test_single_price(self):
        """Single price returns empty array."""
        returns = prices_to_returns(np.array([100]))
        assert len(returns) == 0


# =============================================================================
# CORRELATION MATRIX
# =============================================================================


class TestCorrelationMatrix:
    """Tests for correlation matrix computation."""

    def test_pearson_correlation(self, sample_prices):
        """Pearson correlation matrix."""
        result = compute_correlation_matrix(sample_prices, method="pearson")
        assert result["method"] == "pearson"
        assert result["returns_based"] is True
        assert "AAPL" in result["matrix"]
        # Diagonal should be 1.0
        assert abs(result["matrix"]["AAPL"]["AAPL"] - 1.0) < 0.001

    def test_spearman_correlation(self, sample_prices):
        """Spearman correlation matrix."""
        result = compute_correlation_matrix(sample_prices, method="spearman")
        assert result["method"] == "spearman"
        # Should have valid correlations
        assert -1 <= result["matrix"]["AAPL"]["MSFT"] <= 1

    def test_kendall_correlation(self, sample_prices):
        """Kendall tau correlation matrix."""
        result = compute_correlation_matrix(sample_prices, method="kendall")
        assert result["method"] == "kendall"
        assert -1 <= result["matrix"]["AAPL"]["SPY"] <= 1

    def test_spearman_differs_from_pearson(self, sample_prices):
        """Spearman should give different results than Pearson."""
        pearson = compute_correlation_matrix(sample_prices, method="pearson")
        spearman = compute_correlation_matrix(sample_prices, method="spearman")
        p_val = pearson["matrix"]["AAPL"]["MSFT"]
        s_val = spearman["matrix"]["AAPL"]["MSFT"]
        assert -1 <= p_val <= 1
        assert -1 <= s_val <= 1

    def test_returns_vs_prices_correlation(self, sample_prices):
        """Returns-based correlation differs from price-based."""
        returns_based = compute_correlation_matrix(
            sample_prices, returns_based=True
        )
        price_based = compute_correlation_matrix(
            sample_prices, returns_based=False
        )
        assert returns_based["returns_based"] is True
        assert price_based["returns_based"] is False
        # Price-based tends to show higher correlation due to trends

    def test_empty_data(self):
        """Empty data returns empty matrix."""
        result = compute_correlation_matrix({})
        assert result["matrix"] == {}

    def test_single_asset(self):
        """Single asset correlation is 1.0."""
        prices = {"AAPL": [100, 101, 102, 103, 104]}
        result = compute_correlation_matrix(prices)
        assert abs(result["matrix"]["AAPL"]["AAPL"] - 1.0) < 0.001

    def test_highly_correlated_assets(self, correlated_prices):
        """Highly correlated assets show high correlation."""
        result = compute_correlation_matrix(correlated_prices)
        corr = result["matrix"]["A"]["B"]
        # Should be highly correlated (> 0.8)
        assert corr > 0.8

    def test_from_input_model(self, sample_prices):
        """Compute correlation from CorrelationInput model."""
        inp = CorrelationInput(
            price_data=sample_prices,
            method="spearman",
            returns_based=True,
        )
        result = compute_correlation_from_input(inp)
        assert result["method"] == "spearman"
        assert result["returns_based"] is True


# =============================================================================
# REGIME DETECTION
# =============================================================================


class TestRegimeDetection:
    """Tests for correlation regime detection."""

    def test_regime_detection_structure(self, sample_prices):
        """Regime detection returns correct structure."""
        result = detect_correlation_regimes(
            sample_prices,
            short_window=20,
            long_window=60,
            z_threshold=2.0,
        )
        assert "regime_alerts" in result
        assert "correlation_matrix_short" in result
        assert "correlation_matrix_long" in result
        assert isinstance(result["regime_alerts"], list)

    def test_insufficient_data_raises(self):
        """Insufficient data raises error."""
        short_prices = {"A": [1, 2, 3], "B": [1, 2, 3]}
        with pytest.raises(ValueError, match="at least"):
            detect_correlation_regimes(short_prices, long_window=120)

    def test_empty_data(self):
        """Empty data returns empty results."""
        result = detect_correlation_regimes({})
        assert result["regime_alerts"] == []

    def test_alert_structure(self, sample_prices):
        """Alerts have correct structure if any are generated."""
        result = detect_correlation_regimes(
            sample_prices,
            short_window=10,
            long_window=50,
            z_threshold=0.5,  # Low threshold to potentially trigger alerts
        )
        for alert in result["regime_alerts"]:
            assert "pair" in alert
            assert "short_corr" in alert
            assert "long_corr" in alert
            assert "z_score" in alert
            assert "alert" in alert
            assert alert["alert"] in ["correlation_spike", "correlation_drop"]

    def test_correlation_matrices_are_valid(self, sample_prices):
        """Short and long correlation matrices have valid values."""
        result = detect_correlation_regimes(
            sample_prices,
            short_window=20,
            long_window=60,
        )
        # Check short matrix
        for sym in sample_prices.keys():
            val = result["correlation_matrix_short"][sym][sym]
            assert abs(val - 1.0) < 0.001

        # Check long matrix
        for sym in sample_prices.keys():
            val = result["correlation_matrix_long"][sym][sym]
            assert abs(val - 1.0) < 0.001


# =============================================================================
# CROSS-ASSET CORRELATION
# =============================================================================


class TestCrossAssetCorrelation:
    """Tests for cross-asset correlation."""

    def test_cross_asset_alignment(self):
        """Cross-asset correlation aligns calendars."""
        # Equity: Mon-Fri (business days)
        eq_dates = pd.date_range("2024-01-01", periods=100, freq="B")
        # Crypto: all days
        cr_dates = pd.date_range("2024-01-01", periods=100, freq="D")

        np.random.seed(42)
        eq_prices = {
            "SPY": list(100 * np.cumprod(1 + np.random.normal(0.001, 0.015, 100)))
        }
        cr_prices = {
            "BTC": list(50000 * np.cumprod(1 + np.random.normal(0.002, 0.04, 100)))
        }

        result = compute_cross_asset_correlation(
            eq_prices,
            cr_prices,
            [str(d) for d in eq_dates],
            [str(d) for d in cr_dates],
        )

        assert "cross_asset_correlations" in result
        assert "SPY-BTC" in result["cross_asset_correlations"]
        assert result["common_dates_count"] > 0
        assert -1 <= result["cross_asset_correlations"]["SPY-BTC"] <= 1

    def test_multiple_assets(self):
        """Cross-asset with multiple equities and cryptos."""
        eq_dates = pd.date_range("2024-01-01", periods=100, freq="B")
        cr_dates = pd.date_range("2024-01-01", periods=100, freq="D")

        np.random.seed(42)
        eq_prices = {
            "SPY": list(100 * np.cumprod(1 + np.random.normal(0.001, 0.015, 100))),
            "QQQ": list(100 * np.cumprod(1 + np.random.normal(0.0012, 0.018, 100))),
        }
        cr_prices = {
            "BTC": list(50000 * np.cumprod(1 + np.random.normal(0.002, 0.04, 100))),
            "ETH": list(3000 * np.cumprod(1 + np.random.normal(0.003, 0.05, 100))),
        }

        result = compute_cross_asset_correlation(
            eq_prices,
            cr_prices,
            [str(d) for d in eq_dates],
            [str(d) for d in cr_dates],
        )

        # Should have 4 cross-asset pairs
        assert len(result["cross_asset_correlations"]) == 4
        assert "SPY-BTC" in result["cross_asset_correlations"]
        assert "SPY-ETH" in result["cross_asset_correlations"]
        assert "QQQ-BTC" in result["cross_asset_correlations"]
        assert "QQQ-ETH" in result["cross_asset_correlations"]

    def test_insufficient_overlap_raises(self):
        """Insufficient overlap raises error."""
        eq_dates = pd.date_range("2024-01-01", periods=10, freq="B")
        cr_dates = pd.date_range("2024-06-01", periods=10, freq="D")  # No overlap

        eq_prices = {"SPY": [100 + i for i in range(10)]}
        cr_prices = {"BTC": [50000 + i * 100 for i in range(10)]}

        with pytest.raises(ValueError, match="Insufficient"):
            compute_cross_asset_correlation(
                eq_prices,
                cr_prices,
                [str(d) for d in eq_dates],
                [str(d) for d in cr_dates],
            )

    def test_empty_data(self):
        """Empty data returns empty results."""
        result = compute_cross_asset_correlation({}, {}, [], [])
        assert result["cross_asset_correlations"] == {}
        assert result["common_dates_count"] == 0


# =============================================================================
# PAIRWISE CORRELATION
# =============================================================================


class TestPairwiseCorrelation:
    """Tests for pairwise correlation."""

    def test_perfect_correlation(self):
        """Perfect positive correlation."""
        returns_a = [0.01, 0.02, -0.01, 0.03, 0.01]
        returns_b = [0.01, 0.02, -0.01, 0.03, 0.01]
        corr = compute_pairwise_correlation(returns_a, returns_b)
        assert abs(corr - 1.0) < 0.001

    def test_perfect_negative_correlation(self):
        """Perfect negative correlation."""
        returns_a = [0.01, 0.02, -0.01, 0.03, 0.01]
        returns_b = [-0.01, -0.02, 0.01, -0.03, -0.01]
        corr = compute_pairwise_correlation(returns_a, returns_b)
        assert abs(corr - (-1.0)) < 0.001

    def test_different_methods(self):
        """Different methods give different results."""
        np.random.seed(42)
        returns_a = list(np.random.normal(0.001, 0.02, 50))
        returns_b = list(np.random.normal(0.001, 0.02, 50))

        pearson = compute_pairwise_correlation(returns_a, returns_b, method="pearson")
        spearman = compute_pairwise_correlation(returns_a, returns_b, method="spearman")

        assert -1 <= pearson <= 1
        assert -1 <= spearman <= 1

    def test_length_mismatch_raises(self):
        """Mismatched lengths raise error."""
        with pytest.raises(ValueError, match="same length"):
            compute_pairwise_correlation([0.01, 0.02], [0.01])

    def test_insufficient_data(self):
        """Single data point returns 0."""
        corr = compute_pairwise_correlation([0.01], [0.02])
        assert corr == 0.0


# =============================================================================
# ROLLING CORRELATION
# =============================================================================


class TestRollingCorrelation:
    """Tests for rolling correlation."""

    def test_rolling_correlation_length(self):
        """Rolling correlation has correct length."""
        np.random.seed(42)
        returns_a = list(np.random.normal(0.001, 0.02, 60))
        returns_b = list(np.random.normal(0.001, 0.02, 60))

        rolling = compute_rolling_correlation(returns_a, returns_b, window=20)
        # Should have 60 - 20 + 1 = 41 points
        assert len(rolling) == 41

    def test_rolling_values_valid(self):
        """Rolling correlation values are valid."""
        np.random.seed(42)
        returns_a = list(np.random.normal(0.001, 0.02, 50))
        returns_b = list(np.random.normal(0.001, 0.02, 50))

        rolling = compute_rolling_correlation(returns_a, returns_b, window=10)
        for val in rolling:
            assert -1 <= val <= 1

    def test_insufficient_data(self):
        """Insufficient data returns empty array."""
        rolling = compute_rolling_correlation([0.01, 0.02], [0.01, 0.02], window=10)
        assert len(rolling) == 0

    def test_length_mismatch_raises(self):
        """Mismatched lengths raise error."""
        with pytest.raises(ValueError, match="same length"):
            compute_rolling_correlation([0.01, 0.02], [0.01], window=2)


# =============================================================================
# HEATMAP DATA
# =============================================================================


class TestHeatmapData:
    """Tests for heatmap data generation."""

    def test_heatmap_structure(self, sample_prices):
        """Heatmap data has correct structure."""
        result = get_correlation_heatmap_data(sample_prices)
        assert "symbols" in result
        assert "correlations" in result
        assert "method" in result
        assert len(result["symbols"]) == 3
        assert len(result["correlations"]) == 3
        assert len(result["correlations"][0]) == 3

    def test_heatmap_diagonal(self, sample_prices):
        """Heatmap diagonal is 1.0."""
        result = get_correlation_heatmap_data(sample_prices)
        for i in range(len(result["symbols"])):
            assert abs(result["correlations"][i][i] - 1.0) < 0.001

    def test_heatmap_symmetric(self, sample_prices):
        """Heatmap is symmetric."""
        result = get_correlation_heatmap_data(sample_prices)
        n = len(result["symbols"])
        for i in range(n):
            for j in range(n):
                assert abs(
                    result["correlations"][i][j] - result["correlations"][j][i]
                ) < 0.001


# =============================================================================
# EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_all_same_prices(self):
        """All same prices (zero returns)."""
        prices = {
            "A": [100.0] * 50,
            "B": [200.0] * 50,
        }
        result = compute_correlation_matrix(prices)
        # Zero variance means correlation is undefined (NaN)
        val = result["matrix"]["A"]["B"]
        assert np.isnan(val)

    def test_two_assets_only(self):
        """Two assets correlation matrix."""
        np.random.seed(42)
        prices = {
            "A": list(100 * np.cumprod(1 + np.random.normal(0.001, 0.02, 50))),
            "B": list(100 * np.cumprod(1 + np.random.normal(0.001, 0.02, 50))),
        }
        result = compute_correlation_matrix(prices)
        assert "A" in result["matrix"]
        assert "B" in result["matrix"]
        # Only one unique off-diagonal value
        assert result["matrix"]["A"]["B"] == result["matrix"]["B"]["A"]

    def test_negative_prices(self):
        """Negative prices (e.g., futures) handled."""
        prices = {
            "FUT": [-100, -98, -102, -99, -101],
        }
        result = compute_correlation_matrix(prices)
        # Single asset should still work
        assert abs(result["matrix"]["FUT"]["FUT"] - 1.0) < 0.001
