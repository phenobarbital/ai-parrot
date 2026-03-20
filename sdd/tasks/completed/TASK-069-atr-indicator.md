# TASK-069: ATR Indicator Implementation

**Feature**: TechnicalAnalysisTool Improvements
**Spec**: `sdd/specs/technical-analysis-improvements.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-067
**Assigned-to**: claude-opus-session

---

## Context

ATR (Average True Range) measures volatility in price terms. It's the foundation for volatility-adjusted stop-losses and position sizing. The execution layer places limit orders with stop-losses — ATR tells you how wide those stops should be relative to normal price movement.

Per the open question decision, ATR stop-loss levels must be calculated for BOTH long and short positions separately.

Reference: Spec Section 3 (Module 1: Indicator Extensions)

---

## Scope

- Implement `_calculate_atr()` method on `TechnicalAnalysisTool`
- Calculate True Range using High, Low, Close
- Apply Wilder's smoothing (EMA with alpha=1/period)
- Calculate ATR as percentage of current price
- Calculate stop-loss levels for LONG positions (below price): 1x, 2x, 3x ATR
- Calculate stop-loss levels for SHORT positions (above price): 1x, 2x, 3x ATR
- Return `ATROutput` model

**NOT in scope**:
- ADX calculation (TASK-068)
- EMA calculation (TASK-070)
- Integrating ATR into the main `_execute()` output (TASK-074)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/technical_analysis.py` | MODIFY | Add `_calculate_atr()` method |
| `tests/test_technical_analysis_atr.py` | CREATE | Unit tests for ATR calculation |

---

## Implementation Notes

### Pattern to Follow

```python
def _calculate_atr(
    self,
    df: pd.DataFrame,
    period: int = 14,
    current_price: float | None = None
) -> ATROutput | None:
    """
    Calculate ATR (Average True Range) with stop-loss levels.

    Args:
        df: DataFrame with 'high', 'low', 'close' columns
        period: Smoothing period (default 14)
        current_price: Price for stop-loss calculation (defaults to last close)

    Returns:
        ATROutput model or None if insufficient data
    """
    # Check required columns
    if not all(col in df.columns for col in ['high', 'low', 'close']):
        self.logger.warning("ATR requires high, low, close columns")
        return None

    # Calculate True Range
    tr = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            abs(df['high'] - df['close'].shift(1)),
            abs(df['low'] - df['close'].shift(1))
        )
    )

    # Wilder's smoothing
    alpha = 1 / period
    atr_series = pd.Series(tr).ewm(alpha=alpha, min_periods=period, adjust=False).mean()

    atr_value = float(atr_series.iloc[-1])

    # Use provided price or last close
    if current_price is None:
        current_price = float(df['close'].iloc[-1])

    # Calculate ATR as percentage of price
    atr_percent = (atr_value / current_price) * 100

    # Calculate stop-loss levels for LONG positions (below current price)
    stop_loss_long = {
        "tight_1x": round(current_price - atr_value, 2),
        "standard_2x": round(current_price - 2 * atr_value, 2),
        "wide_3x": round(current_price - 3 * atr_value, 2),
    }

    # Calculate stop-loss levels for SHORT positions (above current price)
    stop_loss_short = {
        "tight_1x": round(current_price + atr_value, 2),
        "standard_2x": round(current_price + 2 * atr_value, 2),
        "wide_3x": round(current_price + 3 * atr_value, 2),
    }

    return ATROutput(
        value=round(atr_value, 4),
        percent=round(atr_percent, 2),
        period=period,
        stop_loss_long=stop_loss_long,
        stop_loss_short=stop_loss_short
    )
```

### Key Constraints

- Must handle NaN values from rolling windows gracefully
- Must check for 'high', 'low', 'close' columns — return None if missing
- Use Wilder's smoothing (alpha=1/period), same as ADX
- Stop-loss for long = price MINUS ATR multiples
- Stop-loss for short = price PLUS ATR multiples
- ATR values validated against TradingView or pandas_ta reference

### References in Codebase

- `parrot/tools/technical_analysis.py` — existing `_calculate_rsi()` method pattern
- Brainstorm doc lines 42-46 — ATR reference implementation

---

## Acceptance Criteria

- [x] `_calculate_atr()` method implemented
- [x] Returns `ATROutput` model with all fields populated
- [x] Gracefully returns None when high/low/close columns missing
- [x] ATR values within 1% of pandas_ta reference for same test data
- [x] `stop_loss_long` contains price - 1x/2x/3x ATR (for long positions)
- [x] `stop_loss_short` contains price + 1x/2x/3x ATR (for short positions)
- [x] `percent` field correctly calculates ATR / price * 100
- [x] All tests pass: `pytest tests/test_technical_analysis_atr.py -v`

---

## Test Specification

```python
# tests/test_technical_analysis_atr.py
import pytest
import pandas as pd
import numpy as np
from parrot.tools.technical_analysis import TechnicalAnalysisTool


@pytest.fixture
def tech_tool():
    return TechnicalAnalysisTool()


@pytest.fixture
def volatile_data():
    """OHLCV data with known volatility."""
    np.random.seed(42)
    n = 50
    close = 100 + np.cumsum(np.random.randn(n))
    return pd.DataFrame({
        'high': close + 2,  # Fixed $2 range
        'low': close - 2,
        'close': close,
    })


class TestATRCalculation:
    def test_atr_calculation(self, tech_tool, volatile_data):
        """ATR calculates correctly."""
        result = tech_tool._calculate_atr(volatile_data)
        assert result is not None
        assert result.value > 0
        assert result.percent > 0

    def test_stop_loss_long(self, tech_tool, volatile_data):
        """Long stop-loss levels are below current price."""
        result = tech_tool._calculate_atr(volatile_data)
        current_price = float(volatile_data['close'].iloc[-1])

        assert result.stop_loss_long["tight_1x"] < current_price
        assert result.stop_loss_long["standard_2x"] < result.stop_loss_long["tight_1x"]
        assert result.stop_loss_long["wide_3x"] < result.stop_loss_long["standard_2x"]

    def test_stop_loss_short(self, tech_tool, volatile_data):
        """Short stop-loss levels are above current price."""
        result = tech_tool._calculate_atr(volatile_data)
        current_price = float(volatile_data['close'].iloc[-1])

        assert result.stop_loss_short["tight_1x"] > current_price
        assert result.stop_loss_short["standard_2x"] > result.stop_loss_short["tight_1x"]
        assert result.stop_loss_short["wide_3x"] > result.stop_loss_short["standard_2x"]

    def test_atr_percent(self, tech_tool, volatile_data):
        """ATR percent calculated correctly."""
        result = tech_tool._calculate_atr(volatile_data)
        current_price = float(volatile_data['close'].iloc[-1])
        expected_percent = (result.value / current_price) * 100
        assert abs(result.percent - expected_percent) < 0.01

    def test_missing_columns(self, tech_tool):
        """ATR returns None when required columns missing."""
        df = pd.DataFrame({'close': [100, 101, 102]})
        result = tech_tool._calculate_atr(df)
        assert result is None

    def test_custom_price(self, tech_tool, volatile_data):
        """ATR respects custom price for stop-loss calculation."""
        custom_price = 150.0
        result = tech_tool._calculate_atr(volatile_data, current_price=custom_price)

        # Stop-loss should be relative to custom price, not last close
        assert result.stop_loss_long["tight_1x"] == round(custom_price - result.value, 2)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/technical-analysis-improvements.spec.md` for full context
2. **Check dependencies** — verify TASK-067 (data models) is in `tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-069-atr-indicator.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-opus-session
**Date**: 2026-03-02
**Notes**:

Implemented `_calculate_atr()` method in `parrot/tools/technical_analysis.py`:

1. **True Range calculation** using max of (high-low, |high-prev_close|, |low-prev_close|)
2. **Wilder's smoothing** (EMA with alpha=1/period) for ATR calculation
3. **ATR percentage** calculation relative to current price
4. **Stop-loss levels for LONG positions**: tight_1x, standard_2x, wide_3x (below price)
5. **Stop-loss levels for SHORT positions**: tight_1x, standard_2x, wide_3x (above price)
6. **Custom price support** for stop-loss calculation scenarios
7. **Graceful error handling** for missing columns, insufficient data, NaN values, and zero price

Created comprehensive test suite at `tests/test_technical_analysis_atr.py` with 23 test cases covering:
- Basic ATR calculation and value validation
- Long/short stop-loss level ordering and symmetry
- ATR percentage calculation
- Missing column handling
- Custom price and period support
- Edge cases (empty data, single row, minimum data)
- Stop-loss multiplier verification
- Output rounding validation

**Deviations from spec**: none
