"""Unit tests for Volatility Analytics."""

import pytest
import numpy as np
from parrot.tools.quant.volatility import (
    compute_realized_volatility,
    compute_volatility_single,
    compute_volatility_cone,
    interpret_volatility_cone,
    compute_iv_rv_spread,
    interpret_iv_rv_spread,
    compute_volatility_term_structure,
    classify_term_structure,
)


@pytest.fixture
def sample_returns():
    """100 days of simulated returns."""
    np.random.seed(42)
    return list(np.random.normal(0.001, 0.02, 100))


@pytest.fixture
def sample_ohlc():
    """OHLC data for advanced estimators."""
    np.random.seed(42)
    n = 100
    close = 100 * np.cumprod(1 + np.random.normal(0.001, 0.02, n))
    # Generate realistic OHLC
    daily_range = np.abs(np.random.normal(0.01, 0.005, n))
    high = close * (1 + daily_range)
    low = close * (1 - daily_range)
    open_ = (high + low) / 2 + np.random.normal(0, 0.5, n)
    return {
        "open": list(open_),
        "high": list(high),
        "low": list(low),
        "close": list(close),
    }


# =============================================================================
# REALIZED VOLATILITY TESTS
# =============================================================================


class TestRealizedVolatility:
    """Tests for compute_realized_volatility function."""

    def test_close_to_close(self, sample_returns):
        """Close-to-close volatility."""
        vol = compute_realized_volatility(sample_returns, window=20)
        # Should have len(returns) - window + 1 values after dropna
        assert len(vol) == len(sample_returns) - 20 + 1
        assert all(v > 0 for v in vol)
        # Annualized vol should be reasonable (10-100% typically)
        assert 0.05 < np.mean(vol) < 1.0

    def test_parkinson_estimator(self, sample_ohlc):
        """Parkinson estimator using high-low."""
        vol = compute_realized_volatility(
            [], window=20, method="parkinson", ohlc_data=sample_ohlc
        )
        assert len(vol) > 0
        assert all(v > 0 for v in vol)

    def test_garman_klass_estimator(self, sample_ohlc):
        """Garman-Klass estimator using OHLC."""
        vol = compute_realized_volatility(
            [], window=20, method="garman_klass", ohlc_data=sample_ohlc
        )
        assert len(vol) > 0
        # Some values might be very small due to GK formula
        assert all(v >= 0 for v in vol)

    def test_parkinson_requires_ohlc(self, sample_returns):
        """Parkinson raises error without OHLC data."""
        with pytest.raises(ValueError, match="ohlc_data required"):
            compute_realized_volatility(sample_returns, method="parkinson")

    def test_garman_klass_requires_ohlc(self, sample_returns):
        """Garman-Klass raises error without OHLC data."""
        with pytest.raises(ValueError, match="ohlc_data required"):
            compute_realized_volatility(sample_returns, method="garman_klass")

    def test_unknown_method(self, sample_returns):
        """Unknown method raises error."""
        with pytest.raises(ValueError, match="Unknown method"):
            compute_realized_volatility(sample_returns, method="unknown")  # type: ignore

    def test_insufficient_data(self):
        """Insufficient data returns empty list."""
        short_returns = [0.01, 0.02, -0.01]
        vol = compute_realized_volatility(short_returns, window=20)
        assert vol == []

    def test_different_annualization(self, sample_returns):
        """Different annualization factors."""
        vol_252 = compute_realized_volatility(sample_returns, annualization=252)
        vol_365 = compute_realized_volatility(sample_returns, annualization=365)
        # Crypto (365) annualization should give higher vol
        assert np.mean(vol_365) > np.mean(vol_252)

    def test_different_windows(self, sample_returns):
        """Different window sizes."""
        vol_10 = compute_realized_volatility(sample_returns, window=10)
        vol_30 = compute_realized_volatility(sample_returns, window=30)
        # Shorter window = more data points
        assert len(vol_10) > len(vol_30)


class TestVolatilitySingle:
    """Tests for compute_volatility_single function."""

    def test_basic_calculation(self, sample_returns):
        """Single volatility calculation."""
        vol = compute_volatility_single(sample_returns)
        assert vol > 0
        assert 0.1 < vol < 1.0  # Reasonable range

    def test_empty_returns(self):
        """Empty returns returns 0."""
        vol = compute_volatility_single([])
        assert vol == 0.0

    def test_single_return(self):
        """Single return returns 0."""
        vol = compute_volatility_single([0.01])
        assert vol == 0.0


# =============================================================================
# VOLATILITY CONE TESTS
# =============================================================================


class TestVolatilityCone:
    """Tests for compute_volatility_cone function."""

    def test_cone_structure(self, sample_returns):
        """Volatility cone returns correct structure."""
        result = compute_volatility_cone(sample_returns, windows=[10, 20, 30])
        assert 10 in result
        assert 20 in result
        assert "current" in result[20]
        assert "percentile" in result[20]
        assert "min" in result[20]
        assert "max" in result[20]
        assert "median" in result[20]

    def test_percentile_range(self, sample_returns):
        """Percentile is between 0 and 100."""
        result = compute_volatility_cone(sample_returns)
        for window, data in result.items():
            assert 0 <= data["percentile"] <= 100

    def test_min_max_relationship(self, sample_returns):
        """Min <= current <= max."""
        result = compute_volatility_cone(sample_returns)
        for window, data in result.items():
            assert data["min"] <= data["current"] <= data["max"]

    def test_insufficient_data_skipped(self):
        """Windows with insufficient data are skipped."""
        short_returns = [0.01, 0.02, -0.01, 0.015]  # Only 4 points
        result = compute_volatility_cone(short_returns, windows=[10, 20])
        assert len(result) == 0  # Both windows need more data

    def test_default_windows(self, sample_returns):
        """Default windows are used."""
        result = compute_volatility_cone(sample_returns)
        # Should have some of the default windows
        assert any(w in result for w in [10, 20, 30])


class TestInterpretVolatilityCone:
    """Tests for interpret_volatility_cone function."""

    def test_interpret_empty(self):
        """Empty cone result."""
        interp = interpret_volatility_cone({})
        assert "Insufficient data" in interp

    def test_interpret_elevated(self):
        """Elevated volatility interpretation."""
        cone = {20: {"current": 0.3, "percentile": 85.0, "min": 0.1, "max": 0.35, "median": 0.2}}
        interp = interpret_volatility_cone(cone)
        assert "ELEVATED" in interp

    def test_interpret_low(self):
        """Low volatility interpretation."""
        cone = {20: {"current": 0.12, "percentile": 15.0, "min": 0.1, "max": 0.35, "median": 0.2}}
        interp = interpret_volatility_cone(cone)
        assert "LOW" in interp

    def test_interpret_normal(self):
        """Normal volatility interpretation."""
        cone = {20: {"current": 0.2, "percentile": 50.0, "min": 0.1, "max": 0.35, "median": 0.2}}
        interp = interpret_volatility_cone(cone)
        assert "NORMAL" in interp


# =============================================================================
# IV VS RV SPREAD TESTS
# =============================================================================


class TestIVRVSpread:
    """Tests for compute_iv_rv_spread function."""

    def test_spread_calculation(self):
        """IV/RV spread is calculated correctly."""
        rv_series = list(np.random.normal(0.30, 0.02, 60))
        result = compute_iv_rv_spread(
            implied_vol=0.35,
            realized_vol_series=rv_series,
        )
        assert "spread" in result
        assert "regime" in result
        assert "implied_vol" in result
        assert "realized_vol" in result
        assert "spread_pct" in result
        assert result["spread"] > 0  # IV > RV

    def test_fear_premium_regime(self):
        """High IV triggers fear_premium regime."""
        rv_series = [0.20] * 60  # Constant 20% RV
        result = compute_iv_rv_spread(
            implied_vol=0.30,  # 50% higher than RV
            realized_vol_series=rv_series,
        )
        assert result["regime"] == "fear_premium"
        assert result["spread_pct"] > 20

    def test_complacent_regime(self):
        """Low IV triggers complacent regime."""
        rv_series = [0.30] * 60  # Constant 30% RV
        result = compute_iv_rv_spread(
            implied_vol=0.20,  # 33% lower than RV
            realized_vol_series=rv_series,
        )
        assert result["regime"] == "complacent"
        assert result["spread_pct"] < -20

    def test_normal_regime(self):
        """Similar IV and RV is normal regime."""
        rv_series = [0.25] * 60
        result = compute_iv_rv_spread(
            implied_vol=0.27,  # Close to RV
            realized_vol_series=rv_series,
        )
        assert result["regime"] == "normal"
        assert -20 <= result["spread_pct"] <= 20

    def test_empty_rv_series(self):
        """Empty RV series handled."""
        result = compute_iv_rv_spread(
            implied_vol=0.25,
            realized_vol_series=[],
        )
        assert result["realized_vol"] == 0.0
        assert result["regime"] == "normal"

    def test_short_rv_series(self):
        """Short RV series still works."""
        rv_series = [0.25, 0.26, 0.24]  # Only 3 points
        result = compute_iv_rv_spread(
            implied_vol=0.25,
            realized_vol_series=rv_series,
            window=20,
        )
        assert result["realized_vol"] > 0


class TestInterpretIVRVSpread:
    """Tests for interpret_iv_rv_spread function."""

    def test_interpret_fear_premium(self):
        """Fear premium interpretation."""
        result = {
            "implied_vol": 0.35,
            "realized_vol": 0.25,
            "spread": 0.10,
            "spread_pct": 40.0,
            "percentile": 90.0,
            "regime": "fear_premium",
        }
        interp = interpret_iv_rv_spread(result)
        assert "FEAR PREMIUM" in interp
        assert "selling premium" in interp.lower()

    def test_interpret_complacent(self):
        """Complacency interpretation."""
        result = {
            "implied_vol": 0.20,
            "realized_vol": 0.30,
            "spread": -0.10,
            "spread_pct": -33.3,
            "percentile": 10.0,
            "regime": "complacent",
        }
        interp = interpret_iv_rv_spread(result)
        assert "COMPLACENCY" in interp
        assert "protection" in interp.lower()

    def test_interpret_normal(self):
        """Normal regime interpretation."""
        result = {
            "implied_vol": 0.25,
            "realized_vol": 0.24,
            "spread": 0.01,
            "spread_pct": 4.2,
            "percentile": 55.0,
            "regime": "normal",
        }
        interp = interpret_iv_rv_spread(result)
        assert "NORMAL" in interp


# =============================================================================
# VOLATILITY TERM STRUCTURE TESTS
# =============================================================================


class TestVolatilityTermStructure:
    """Tests for compute_volatility_term_structure function."""

    def test_term_structure(self, sample_returns):
        """Term structure calculation."""
        result = compute_volatility_term_structure(sample_returns)
        assert len(result) > 0
        # Should have multiple windows
        assert any(w in result for w in [5, 10, 20])

    def test_custom_windows(self, sample_returns):
        """Custom windows."""
        result = compute_volatility_term_structure(sample_returns, windows=[10, 30, 60])
        assert 10 in result
        assert 30 in result

    def test_insufficient_data(self):
        """Insufficient data for some windows."""
        short_returns = [0.01] * 15
        result = compute_volatility_term_structure(short_returns, windows=[10, 20, 30])
        assert 10 in result
        assert 20 not in result  # Not enough data


class TestClassifyTermStructure:
    """Tests for classify_term_structure function."""

    def test_contango(self):
        """Normal term structure (contango)."""
        term_structure = {5: 0.20, 20: 0.25, 60: 0.30}
        result = classify_term_structure(term_structure)
        assert result == "contango"

    def test_backwardation(self):
        """Inverted term structure (backwardation/stress)."""
        term_structure = {5: 0.35, 20: 0.30, 60: 0.20}
        result = classify_term_structure(term_structure)
        assert result == "backwardation"

    def test_flat(self):
        """Flat term structure."""
        term_structure = {5: 0.25, 20: 0.26, 60: 0.25}
        result = classify_term_structure(term_structure)
        assert result == "flat"

    def test_insufficient_data(self):
        """Insufficient data."""
        term_structure = {20: 0.25}
        result = classify_term_structure(term_structure)
        assert result == "insufficient_data"


# =============================================================================
# EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_all_same_returns(self):
        """All same returns (zero volatility)."""
        returns = [0.01] * 100
        vol = compute_realized_volatility(returns, window=20)
        assert all(v == 0.0 for v in vol)

    def test_negative_returns(self):
        """Negative returns work correctly."""
        np.random.seed(42)
        returns = list(np.random.normal(-0.01, 0.02, 100))  # Negative drift
        vol = compute_realized_volatility(returns, window=20)
        assert len(vol) > 0
        assert all(v > 0 for v in vol)

    def test_high_volatility(self):
        """High volatility data."""
        np.random.seed(42)
        returns = list(np.random.normal(0.001, 0.10, 100))  # 10% daily vol
        vol = compute_realized_volatility(returns, window=20)
        # Annualized should be very high
        assert np.mean(vol) > 1.0

    def test_ohlc_with_zeros(self):
        """OHLC with zero values handled."""
        ohlc_data = {
            "open": [100] * 30,
            "high": [105] * 30,
            "low": [0] * 30,  # Zero lows
            "close": [102] * 30,
        }
        # Should handle gracefully (may return empty or nan-free list)
        vol = compute_realized_volatility([], window=10, method="parkinson", ohlc_data=ohlc_data)
        # Result should be nan-free
        assert all(not np.isnan(v) for v in vol)

    def test_extreme_iv_rv_spread(self):
        """Extreme IV/RV spread values."""
        rv_series = [0.10] * 60
        result = compute_iv_rv_spread(
            implied_vol=1.0,  # 1000% higher than RV
            realized_vol_series=rv_series,
        )
        assert result["regime"] == "fear_premium"
        assert result["spread_pct"] > 100
