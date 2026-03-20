# TASK-068: ADX Indicator Implementation

**Feature**: TechnicalAnalysisTool Improvements
**Spec**: `sdd/specs/technical-analysis-improvements.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-067
**Assigned-to**: claude-opus-session

---

## Context

ADX (Average Directional Index) measures trend strength regardless of direction. It's the only indicator that tells you *how strong* a trend is. Without it, analysts can't distinguish between a weak drift and a powerful move. The risk analyst needs this to size positions appropriately.

ADX requires High, Low, Close data (not just Close).

Reference: Spec Section 3 (Module 1: Indicator Extensions)

---

## Scope

- Implement `_calculate_adx()` method on `TechnicalAnalysisTool`
- Calculate +DI (positive directional indicator) and -DI (negative directional indicator)
- Calculate ADX value using Wilder's smoothing (EMA with alpha=1/period)
- Classify trend strength: "absent" (<20), "weak" (20-25), "strong" (25-50), "extreme" (>50)
- Classify trend direction: "bullish" (+DI > -DI), "bearish" (-DI > +DI), "undefined" (ADX < 20)
- Return `ADXOutput` model

**NOT in scope**:
- ATR calculation (TASK-069)
- EMA calculation (TASK-070)
- Integrating ADX into the main `_execute()` output (TASK-074)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/technical_analysis.py` | MODIFY | Add `_calculate_adx()` method |
| `tests/test_technical_analysis_adx.py` | CREATE | Unit tests for ADX calculation |

---

## Implementation Notes

### Pattern to Follow

```python
def _calculate_adx(self, df: pd.DataFrame, period: int = 14) -> ADXOutput | None:
    """
    Calculate ADX (Average Directional Index) with +DI and -DI.

    Args:
        df: DataFrame with 'high', 'low', 'close' columns
        period: Smoothing period (default 14)

    Returns:
        ADXOutput model or None if insufficient data
    """
    # Check required columns
    if not all(col in df.columns for col in ['high', 'low', 'close']):
        self.logger.warning("ADX requires high, low, close columns")
        return None

    # Calculate True Range
    tr = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            abs(df['high'] - df['close'].shift(1)),
            abs(df['low'] - df['close'].shift(1))
        )
    )

    # Calculate Directional Movement
    delta_high = df['high'].diff()
    delta_low = -df['low'].diff()

    plus_dm = np.where((delta_high > delta_low) & (delta_high > 0), delta_high, 0)
    minus_dm = np.where((delta_low > delta_high) & (delta_low > 0), delta_low, 0)

    # Wilder's smoothing (EMA with alpha=1/period)
    alpha = 1 / period
    atr = pd.Series(tr).ewm(alpha=alpha, min_periods=period, adjust=False).mean()

    plus_di = 100 * pd.Series(plus_dm).ewm(alpha=alpha, min_periods=period, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm).ewm(alpha=alpha, min_periods=period, adjust=False).mean() / atr

    # Calculate DX and ADX
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.ewm(alpha=alpha, min_periods=period, adjust=False).mean()

    # Get latest values
    adx_value = float(adx.iloc[-1])
    plus_di_value = float(plus_di.iloc[-1])
    minus_di_value = float(minus_di.iloc[-1])

    # Classify trend strength
    if adx_value < 20:
        trend_strength = "absent"
    elif adx_value < 25:
        trend_strength = "weak"
    elif adx_value < 50:
        trend_strength = "strong"
    else:
        trend_strength = "extreme"

    # Classify trend direction
    if adx_value < 20:
        trend_direction = "undefined"
    elif plus_di_value > minus_di_value:
        trend_direction = "bullish"
    else:
        trend_direction = "bearish"

    return ADXOutput(
        value=round(adx_value, 2),
        plus_di=round(plus_di_value, 2),
        minus_di=round(minus_di_value, 2),
        trend_strength=trend_strength,
        trend_direction=trend_direction
    )
```

### Key Constraints

- Must handle NaN values from rolling windows gracefully
- Must check for 'high', 'low', 'close' columns — return None if missing
- Use Wilder's smoothing (alpha=1/period), NOT standard EMA span
- ADX values validated against TradingView or pandas_ta reference

### References in Codebase

- `parrot/tools/technical_analysis.py` — existing `_calculate_rsi()` method pattern
- Brainstorm doc lines 34-39 — ADX reference implementation

---

## Acceptance Criteria

- [x] `_calculate_adx()` method implemented
- [x] Returns `ADXOutput` model with all 5 fields populated
- [x] Gracefully returns None when high/low/close columns missing
- [x] ADX values within 1% of pandas_ta reference for same test data
- [x] Trend strength classification matches thresholds: absent(<20), weak(20-25), strong(25-50), extreme(>50)
- [x] Trend direction correctly identifies bullish (+DI > -DI) vs bearish
- [x] All tests pass: `pytest tests/test_technical_analysis_adx.py -v`

---

## Test Specification

```python
# tests/test_technical_analysis_adx.py
import pytest
import pandas as pd
import numpy as np
from parrot.tools.technical_analysis import TechnicalAnalysisTool


@pytest.fixture
def tech_tool():
    return TechnicalAnalysisTool()


@pytest.fixture
def bullish_trending_data():
    """OHLCV data with clear uptrend (ADX > 25, +DI > -DI)."""
    np.random.seed(42)
    n = 100
    prices = 100 + np.cumsum(np.random.randn(n) * 0.5 + 0.3)  # Upward drift
    return pd.DataFrame({
        'high': prices + np.random.rand(n) * 2,
        'low': prices - np.random.rand(n) * 2,
        'close': prices,
    })


@pytest.fixture
def sideways_data():
    """OHLCV data with no trend (ADX < 20)."""
    np.random.seed(42)
    n = 100
    prices = 100 + np.sin(np.linspace(0, 4*np.pi, n)) * 3  # Oscillating
    return pd.DataFrame({
        'high': prices + np.random.rand(n) * 1,
        'low': prices - np.random.rand(n) * 1,
        'close': prices,
    })


class TestADXCalculation:
    def test_bullish_trend_detection(self, tech_tool, bullish_trending_data):
        """ADX detects bullish trend correctly."""
        result = tech_tool._calculate_adx(bullish_trending_data)
        assert result is not None
        assert result.trend_direction == "bullish"
        assert result.plus_di > result.minus_di

    def test_trendless_market(self, tech_tool, sideways_data):
        """ADX identifies trendless market."""
        result = tech_tool._calculate_adx(sideways_data)
        assert result is not None
        assert result.trend_strength == "absent"
        assert result.trend_direction == "undefined"

    def test_missing_columns(self, tech_tool):
        """ADX returns None when required columns missing."""
        df = pd.DataFrame({'close': [100, 101, 102]})
        result = tech_tool._calculate_adx(df)
        assert result is None

    def test_adx_value_range(self, tech_tool, bullish_trending_data):
        """ADX value is between 0 and 100."""
        result = tech_tool._calculate_adx(bullish_trending_data)
        assert 0 <= result.value <= 100

    def test_trend_strength_thresholds(self, tech_tool):
        """Verify trend strength classification thresholds."""
        # This test would need mock data producing specific ADX values
        # to verify exact threshold behavior
        pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/technical-analysis-improvements.spec.md` for full context
2. **Check dependencies** — verify TASK-067 (data models) is in `tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-068-adx-indicator.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-opus-session
**Date**: 2026-03-02
**Notes**:

Implemented `_calculate_adx()` method in `parrot/tools/technical_analysis.py`:

1. **True Range calculation** using high, low, close columns
2. **Directional Movement (+DM/-DM)** calculation with proper conditions
3. **Wilder's smoothing** (EMA with alpha=1/period) for ATR, +DI, -DI, and ADX
4. **Division-by-zero protection** using np.nan replacement
5. **NaN handling** with graceful return of None
6. **Trend strength classification**: absent(<20), weak(20-25), strong(25-50), extreme(>50)
7. **Trend direction classification**: bullish (+DI > -DI), bearish (-DI > +DI), undefined (ADX < 20)

Created comprehensive test suite at `tests/test_technical_analysis_adx.py` with 19 test cases:
- Bullish/bearish/trendless market detection
- Missing column handling
- Insufficient data handling
- Custom period support
- Edge cases (constant prices, NaN values, empty dataframe)
- Output validation and serialization

**Deviations from spec**: none
