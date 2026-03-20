# TASK-088: Volatility Analytics

**Feature**: FEAT-017 QuantToolkit
**Spec**: `sdd/specs/quant-toolkit.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-084
**Assigned-to**: claude-opus-session

---

## Context

This task implements volatility analytics for the sentiment analyst crew. It provides multiple volatility estimators, volatility cone analysis, and implied vs realized volatility spread analysis.

Reference: Spec Section 3 (Module 5: Volatility Analytics).

---

## Scope

- Implement realized volatility estimators:
  - Close-to-close (standard deviation of log returns)
  - Parkinson (uses high-low range, more efficient)
  - Garman-Klass (uses OHLC, most efficient)
- Implement volatility cone:
  - Percentile ranks across multiple lookback windows
  - Answers: "Is current 20-day vol high or low relative to history?"
- Implement IV vs RV spread analysis:
  - Compare implied volatility to realized volatility
  - Classify regime: "fear_premium" | "complacent" | "normal"
- Write comprehensive unit tests

**NOT in scope**:
- Implied volatility calculation (callers provide IV from options data)
- The main QuantToolkit class (TASK-079)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/quant/volatility.py` | CREATE | Volatility analytics |
| `tests/tools/test_quant/test_volatility.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

```python
import numpy as np
import pandas as pd
from typing import Literal


def compute_realized_volatility(
    returns: list[float],
    window: int = 20,
    annualization: int = 252,
    method: Literal["close_to_close", "parkinson", "garman_klass"] = "close_to_close",
    ohlc_data: dict[str, list[float]] | None = None,
) -> list[float]:
    """
    Compute rolling realized volatility.

    Methods:
    - close_to_close: Standard deviation of log returns (most common)
    - parkinson: Uses high-low range, ~5x more efficient than close-to-close
    - garman_klass: Uses OHLC, most efficient estimator

    Args:
        returns: Daily return series (for close_to_close)
        window: Rolling window size
        annualization: 252 for stocks, 365 for crypto
        method: Volatility estimator method
        ohlc_data: Required for parkinson/garman_klass: {"high": [], "low": [], "open": [], "close": []}

    Returns:
        List of rolling annualized volatility values
    """
    if method == "close_to_close":
        returns_arr = np.array(returns)
        rolling_std = pd.Series(returns_arr).rolling(window).std()
        return list(rolling_std.dropna() * np.sqrt(annualization))

    elif method == "parkinson":
        if ohlc_data is None:
            raise ValueError("ohlc_data required for Parkinson estimator")
        high = np.array(ohlc_data["high"])
        low = np.array(ohlc_data["low"])
        # Parkinson: sigma^2 = (1/4*ln(2)) * ln(H/L)^2
        log_hl = np.log(high / low) ** 2
        factor = 1 / (4 * np.log(2))
        rolling_var = pd.Series(log_hl).rolling(window).mean() * factor
        return list(np.sqrt(rolling_var.dropna() * annualization))

    elif method == "garman_klass":
        if ohlc_data is None:
            raise ValueError("ohlc_data required for Garman-Klass estimator")
        high = np.array(ohlc_data["high"])
        low = np.array(ohlc_data["low"])
        open_ = np.array(ohlc_data["open"])
        close = np.array(ohlc_data["close"])
        # Garman-Klass: 0.5*ln(H/L)^2 - (2*ln(2)-1)*ln(C/O)^2
        log_hl_sq = np.log(high / low) ** 2
        log_co_sq = np.log(close / open_) ** 2
        gk_var = 0.5 * log_hl_sq - (2 * np.log(2) - 1) * log_co_sq
        rolling_var = pd.Series(gk_var).rolling(window).mean()
        return list(np.sqrt(rolling_var.dropna() * annualization))

    else:
        raise ValueError(f"Unknown method: {method}")


def compute_volatility_cone(
    returns: list[float],
    windows: list[int] = [10, 20, 30, 60, 90, 120],
) -> dict:
    """
    Compute percentile ranks of current volatility across multiple windows.

    Answers: "Is current 20-day vol high or low relative to history?"

    Returns:
        {
            window: {
                "current": float,
                "percentile": float (0-100),
                "min": float,
                "max": float,
                "median": float,
            }
        }
    """
    returns_arr = np.array(returns)
    annualization = 252  # Default to equity

    result = {}
    for window in windows:
        if len(returns_arr) < window + 1:
            continue

        # Compute rolling volatility history
        rolling_vol = pd.Series(returns_arr).rolling(window).std() * np.sqrt(annualization)
        rolling_vol = rolling_vol.dropna()

        if len(rolling_vol) == 0:
            continue

        current_vol = rolling_vol.iloc[-1]
        percentile = (rolling_vol < current_vol).mean() * 100

        result[window] = {
            "current": round(float(current_vol), 4),
            "percentile": round(float(percentile), 1),
            "min": round(float(rolling_vol.min()), 4),
            "max": round(float(rolling_vol.max()), 4),
            "median": round(float(rolling_vol.median()), 4),
        }

    return result


def compute_iv_rv_spread(
    implied_vol: float,
    realized_vol_series: list[float],
    window: int = 20,
) -> dict:
    """
    Compute IV vs RV spread and classify the regime.

    - IV >> RV: Fear premium is elevated (contrarian buy signal)
    - IV << RV: Complacency (contrarian sell signal)
    - IV ≈ RV: Normal regime

    Args:
        implied_vol: Current implied volatility (annualized, from options)
        realized_vol_series: Historical realized vol series
        window: Window for current RV calculation

    Returns:
        {
            "implied_vol": float,
            "realized_vol": float,
            "spread": float (IV - RV),
            "spread_pct": float ((IV - RV) / RV * 100),
            "percentile": float (where current spread falls historically),
            "regime": "fear_premium" | "complacent" | "normal",
        }
    """
    rv_arr = np.array(realized_vol_series)

    # Current realized vol (latest value or average of recent window)
    current_rv = np.mean(rv_arr[-window:]) if len(rv_arr) >= window else np.mean(rv_arr)

    spread = implied_vol - current_rv
    spread_pct = (spread / current_rv * 100) if current_rv > 0 else 0

    # Compute historical spread percentile
    # We'd need historical IV to do this properly, but we can use RV-based estimate
    historical_spreads = rv_arr[window:] - pd.Series(rv_arr).rolling(window).mean().dropna().values
    if len(historical_spreads) > 0:
        percentile = (historical_spreads < spread).mean() * 100
    else:
        percentile = 50.0  # Default to middle

    # Classify regime
    if spread_pct > 20:  # IV 20%+ higher than RV
        regime = "fear_premium"
    elif spread_pct < -20:  # IV 20%+ lower than RV
        regime = "complacent"
    else:
        regime = "normal"

    return {
        "implied_vol": round(implied_vol, 4),
        "realized_vol": round(current_rv, 4),
        "spread": round(spread, 4),
        "spread_pct": round(spread_pct, 1),
        "percentile": round(percentile, 1),
        "regime": regime,
    }
```

### Key Constraints
- Close-to-close uses standard deviation of returns (not log returns for simplicity)
- Parkinson requires high/low data
- Garman-Klass requires OHLC data
- Volatility cone windows must have sufficient data
- IV/RV spread thresholds: +/- 20% for regime classification

### References in Codebase
- Spec Section 3 Module 5 for volatility estimator formulas
- VIX methodology for IV/RV spread interpretation

---

## Acceptance Criteria

- [x] Three volatility estimators implemented (close-to-close, Parkinson, Garman-Klass)
- [x] Volatility cone produces percentile ranks for all specified windows
- [x] IV/RV spread correctly classifies regimes
- [x] All tests pass: `pytest tests/tools/test_quant/test_volatility.py -v`
- [x] Edge cases handled (insufficient data, zero values)

---

## Test Specification

```python
# tests/tools/test_quant/test_volatility.py
import pytest
import numpy as np
from parrot.tools.quant.volatility import (
    compute_realized_volatility, compute_volatility_cone, compute_iv_rv_spread
)


@pytest.fixture
def sample_returns():
    """60 days of simulated returns."""
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


class TestRealizedVolatility:
    def test_close_to_close(self, sample_returns):
        """Close-to-close volatility."""
        vol = compute_realized_volatility(sample_returns, window=20)
        assert len(vol) == len(sample_returns) - 20 + 1
        assert all(v > 0 for v in vol)
        # Annualized vol should be reasonable (10-50% typically)
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

    def test_parkinson_requires_ohlc(self, sample_returns):
        """Parkinson raises error without OHLC data."""
        with pytest.raises(ValueError, match="ohlc_data required"):
            compute_realized_volatility(
                sample_returns, method="parkinson"
            )


class TestVolatilityCone:
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

    def test_insufficient_data_skipped(self):
        """Windows with insufficient data are skipped."""
        short_returns = [0.01, 0.02, -0.01, 0.015]  # Only 4 points
        result = compute_volatility_cone(short_returns, windows=[10, 20])
        assert len(result) == 0  # Both windows need more data


class TestIVRVSpread:
    def test_spread_calculation(self, sample_returns):
        """IV/RV spread is calculated correctly."""
        # Simulate realized vol around 30%
        rv_series = list(np.random.normal(0.30, 0.02, 60))
        result = compute_iv_rv_spread(
            implied_vol=0.35,  # IV slightly higher
            realized_vol_series=rv_series,
        )
        assert "spread" in result
        assert "regime" in result
        assert result["spread"] > 0  # IV > RV

    def test_fear_premium_regime(self):
        """High IV triggers fear_premium regime."""
        rv_series = [0.20] * 60  # Constant 20% RV
        result = compute_iv_rv_spread(
            implied_vol=0.30,  # 50% higher than RV
            realized_vol_series=rv_series,
        )
        assert result["regime"] == "fear_premium"

    def test_complacent_regime(self):
        """Low IV triggers complacent regime."""
        rv_series = [0.30] * 60  # Constant 30% RV
        result = compute_iv_rv_spread(
            implied_vol=0.20,  # 33% lower than RV
            realized_vol_series=rv_series,
        )
        assert result["regime"] == "complacent"

    def test_normal_regime(self):
        """Similar IV and RV is normal regime."""
        rv_series = [0.25] * 60
        result = compute_iv_rv_spread(
            implied_vol=0.27,  # Close to RV
            realized_vol_series=rv_series,
        )
        assert result["regime"] == "normal"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/quant-toolkit.spec.md` for full context
2. **Check dependencies** — verify TASK-084 is in `tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-081-volatility-analytics.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-opus-session
**Date**: 2026-03-02
**Notes**:
- Implemented all three volatility estimators (close-to-close, Parkinson, Garman-Klass)
- Added volatility cone with percentile ranking across configurable windows
- Implemented IV vs RV spread analysis with regime classification (fear_premium, complacent, normal)
- Added volatility term structure analysis with contango/backwardation detection
- Added interpretation functions for cone and IV/RV spread results
- Fixed array alignment bug in `compute_iv_rv_spread` historical percentile calculation
- 42 tests passing with comprehensive edge case coverage

**Deviations from spec**:
- Added `compute_volatility_single()` for single-point volatility calculation
- Added `compute_volatility_term_structure()` and `classify_term_structure()` for term structure analysis
- Added `interpret_volatility_cone()` and `interpret_iv_rv_spread()` helper functions
- Added defensive handling for zero/negative values in OHLC data (prevents NaN propagation)
