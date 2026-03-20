# TASK-074: Output Restructuring

**Feature**: TechnicalAnalysisTool Improvements
**Spec**: `sdd/specs/technical-analysis-improvements.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-067, TASK-068, TASK-069, TASK-070, TASK-071
**Assigned-to**: claude-opus-session

---

## Context

The current `_execute()` method returns a flat output structure. This task restructures the output to a semantically grouped format while maintaining backward compatibility via a `legacy_format=True` parameter.

Reference: Spec Section 3 (Module 5: Output Restructuring)

---

## Scope

- Modify `_execute()` to produce new nested output structure
- Add `legacy_format: bool = False` parameter for backward compatibility
- Integrate new indicators (ADX, ATR, EMA) into output
- Integrate signal engine output (`List[TechnicalSignal]`)
- Add `risk_context` section with ATR stop-loss and volatility metrics

**New Output Structure:**
```python
{
    "symbol": "AAPL",
    "asset_type": "stock",
    "timestamp": "2025-01-15T16:00:00Z",
    "price": {
        "current": 185.00,
        "change_1d": 2.30,
        "change_1d_pct": 1.26,
    },
    "indicators": {
        "trend": {
            "sma_20": 182.50,
            "sma_50": 178.30,
            "sma_200": 170.15,
            "ema_12": 183.90,
            "ema_26": 181.20,
            "adx": {"value": 32.5, "plus_di": 28.3, "minus_di": 15.7,
                    "trend_strength": "strong", "trend_direction": "bullish"},
        },
        "momentum": {
            "rsi_14": {"value": 65.0, "zone": "bullish"},
            "macd": {"line": 1.85, "signal": 1.20, "histogram": 0.65,
                     "prev_histogram": 0.45, "histogram_rising": True},
        },
        "volatility": {
            "bollinger": {"upper": 190.0, "middle": 182.5, "lower": 175.0,
                          "bandwidth_pct": 8.22, "price_position": "mid_upper"},
            "atr": {"value": 3.42, "percent": 1.85, "stop_loss_2x": 178.16},
        },
        "volume": {
            "current": 50000000,
            "avg_20d": 35000000,
            "ratio": 1.43,
            "is_high": False,
        },
    },
    "signals": [TechnicalSignal, ...],  # From signal engine
    "risk_context": {
        "atr_stop_long_2x": 178.16,
        "atr_stop_short_2x": 191.84,
        "volatility_annualized_pct": 28.5,
    },
}
```

**NOT in scope**:
- CompositeScore in main output (that's a separate tool now)
- Multi-timeframe data in main output (separate method)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/technical_analysis.py` | MODIFY | Restructure `_execute()` output |
| `tests/test_technical_analysis_output.py` | CREATE | Tests for new output format |

---

## Implementation Notes

### Pattern to Follow

```python
async def _execute(
    self,
    symbol: str,
    asset_type: str,
    source: str = 'alpaca',
    interval: str = '1d',
    lookback_days: int = 365,
    legacy_format: bool = False,  # NEW parameter
) -> dict:
    """
    Execute the technical analysis.

    Args:
        ...
        legacy_format: If True, return old flat structure for backward compatibility
    """
    # ... existing data fetching logic ...

    # Calculate all indicators (including new ones)
    df['SMA_50'] = df['close'].rolling(window=50).mean()
    df['SMA_200'] = df['close'].rolling(window=200).mean()
    df['EMA_12'] = self._calculate_ema(df['close'], 12)
    df['EMA_26'] = self._calculate_ema(df['close'], 26)
    # ... RSI, MACD, BBands as before ...

    # New indicators
    adx_output = self._calculate_adx(df)
    atr_output = self._calculate_atr(df)

    # Generate signals
    indicators_dict = {
        "SMA_50": float(df['SMA_50'].iloc[-1]),
        "SMA_200": float(df['SMA_200'].iloc[-1]),
        "RSI_14": float(df['RSI_14'].iloc[-1]),
        # ... etc
    }
    signals = self._generate_signals(df, indicators_dict, adx_output)

    if legacy_format:
        # Return old structure for backward compatibility
        return self._build_legacy_output(df, indicators_dict, signals)

    # Build new structured output
    return self._build_structured_output(
        symbol=symbol,
        asset_type=asset_type,
        df=df,
        adx_output=adx_output,
        atr_output=atr_output,
        signals=signals,
    )


def _build_structured_output(
    self,
    symbol: str,
    asset_type: str,
    df: pd.DataFrame,
    adx_output: ADXOutput | None,
    atr_output: ATROutput | None,
    signals: list[TechnicalSignal],
) -> dict:
    """Build the new nested output structure."""
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else last

    current_price = float(last['close'])
    price_change = current_price - float(prev['close'])
    price_change_pct = (price_change / float(prev['close'])) * 100

    # Build indicators section
    indicators = {
        "trend": {
            "sma_20": self._safe_float(df.get('SMA_20', pd.Series()).iloc[-1] if 'SMA_20' in df else None),
            "sma_50": self._safe_float(last.get('SMA_50')),
            "sma_200": self._safe_float(last.get('SMA_200')),
            "ema_12": self._safe_float(last.get('EMA_12')),
            "ema_26": self._safe_float(last.get('EMA_26')),
            "adx": adx_output.model_dump() if adx_output else None,
        },
        "momentum": {
            "rsi_14": {
                "value": self._safe_float(last.get('RSI_14')),
                "zone": self._get_rsi_zone(last.get('RSI_14')),
            },
            "macd": {
                "line": self._safe_float(last.get('MACD')),
                "signal": self._safe_float(last.get('MACD_Signal')),
                "histogram": self._safe_float(last.get('MACD_Hist')),
                "prev_histogram": self._safe_float(prev.get('MACD_Hist')),
                "histogram_rising": (
                    last.get('MACD_Hist', 0) > prev.get('MACD_Hist', 0)
                    if pd.notna(last.get('MACD_Hist')) else None
                ),
            },
        },
        "volatility": {
            "bollinger": {
                "upper": self._safe_float(last.get('BB_Upper')),
                "middle": self._safe_float(last.get('BB_Mid')),
                "lower": self._safe_float(last.get('BB_Lower')),
                "bandwidth_pct": self._calculate_bb_bandwidth(last),
                "price_position": self._get_bb_position(last),
            },
            "atr": {
                "value": atr_output.value if atr_output else None,
                "percent": atr_output.percent if atr_output else None,
                "stop_loss_long_2x": atr_output.stop_loss_long["standard_2x"] if atr_output else None,
                "stop_loss_short_2x": atr_output.stop_loss_short["standard_2x"] if atr_output else None,
            } if atr_output else None,
        },
        "volume": {
            "current": self._safe_float(last.get('volume')),
            "avg_20d": self._safe_float(last.get('Vol_Avg_20')),
            "ratio": round(
                float(last['volume']) / float(last['Vol_Avg_20']), 2
            ) if pd.notna(last.get('volume')) and pd.notna(last.get('Vol_Avg_20')) else None,
            "is_high": (
                float(last['volume']) > float(last['Vol_Avg_20']) * 1.5
            ) if pd.notna(last.get('volume')) and pd.notna(last.get('Vol_Avg_20')) else False,
        },
    }

    # Build risk context
    risk_context = {
        "atr_stop_long_2x": atr_output.stop_loss_long["standard_2x"] if atr_output else None,
        "atr_stop_short_2x": atr_output.stop_loss_short["standard_2x"] if atr_output else None,
        "volatility_annualized_pct": self._calculate_annualized_vol(df),
    }

    return {
        "symbol": symbol,
        "asset_type": asset_type,
        "timestamp": str(last.get('timestamp', '')),
        "price": {
            "current": round(current_price, 2),
            "change_1d": round(price_change, 2),
            "change_1d_pct": round(price_change_pct, 2),
        },
        "indicators": indicators,
        "signals": [s.__dict__ for s in signals],
        "risk_context": risk_context,
    }


def _build_legacy_output(
    self,
    df: pd.DataFrame,
    indicators: dict,
    signals: list[TechnicalSignal],
) -> dict:
    """Build the old flat output structure for backward compatibility."""
    last = df.iloc[-1]

    # Convert TechnicalSignal objects to flat strings (old format)
    flat_signals = [s.description for s in signals]

    return {
        "symbol": ...,  # Same as before
        "timestamp": str(last['timestamp']),
        "price": float(last['close']),
        "indicators": {
            "SMA_50": indicators.get("SMA_50"),
            "SMA_200": indicators.get("SMA_200"),
            "RSI_14": indicators.get("RSI_14"),
            "MACD": {
                "value": ...,
                "signal": ...,
                "hist": ...,
            },
            "BBands": {...},
        },
        "signals": flat_signals,  # Flat strings, not objects
        "volume": float(last['volume']) if 'volume' in df else None,
    }


def _safe_float(self, value) -> float | None:
    """Safely convert value to float, handling NaN."""
    if pd.isna(value):
        return None
    return round(float(value), 2)
```

### Key Constraints

- `legacy_format=True` must return structure identical to current output
- New format groups indicators by category: trend, momentum, volatility, volume
- Signals are now `TechnicalSignal` objects (or their dict representation)
- `risk_context` includes both long and short ATR stop-loss levels
- Handle NaN values gracefully — return `None` instead of NaN

### References in Codebase

- `parrot/tools/technical_analysis.py` lines 200-251 — current output structure
- Spec section 3.5 — new output structure specification

---

## Acceptance Criteria

- [ ] `_execute()` accepts `legacy_format` parameter
- [ ] `legacy_format=True` returns identical structure to current output
- [ ] New format groups indicators into trend/momentum/volatility/volume
- [ ] ADX output integrated into `indicators.trend.adx`
- [ ] ATR output integrated into `indicators.volatility.atr`
- [ ] EMA values included in `indicators.trend`
- [ ] Signals returned as structured objects (not flat strings)
- [ ] `risk_context` includes ATR stop-losses for both long and short
- [ ] NaN values converted to `None` in output
- [ ] All tests pass: `pytest tests/test_technical_analysis_output.py -v`

---

## Test Specification

```python
# tests/test_technical_analysis_output.py
import pytest
import pandas as pd
import numpy as np
from parrot.tools.technical_analysis import TechnicalAnalysisTool


@pytest.fixture
def tech_tool():
    return TechnicalAnalysisTool()


@pytest.fixture
def sample_ohlcv():
    """Sample OHLCV data for testing."""
    np.random.seed(42)
    n = 250
    close = 100 + np.cumsum(np.random.randn(n))
    return pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=n),
        'high': close + np.random.rand(n) * 2,
        'low': close - np.random.rand(n) * 2,
        'close': close,
        'volume': np.random.randint(1000000, 5000000, n),
    })


class TestOutputStructure:
    @pytest.mark.asyncio
    async def test_new_format_structure(self, tech_tool, sample_ohlcv):
        """New format has correct nested structure."""
        # Mock the data fetching
        # ... setup mock ...

        result = await tech_tool._execute(
            symbol="TEST",
            asset_type="stock",
            legacy_format=False,
        )

        # Check top-level keys
        assert "symbol" in result
        assert "asset_type" in result
        assert "price" in result
        assert "indicators" in result
        assert "signals" in result
        assert "risk_context" in result

        # Check price structure
        assert "current" in result["price"]
        assert "change_1d" in result["price"]
        assert "change_1d_pct" in result["price"]

        # Check indicators structure
        assert "trend" in result["indicators"]
        assert "momentum" in result["indicators"]
        assert "volatility" in result["indicators"]
        assert "volume" in result["indicators"]

        # Check trend indicators
        trend = result["indicators"]["trend"]
        assert "sma_50" in trend
        assert "sma_200" in trend
        assert "ema_12" in trend
        assert "ema_26" in trend
        assert "adx" in trend

    @pytest.mark.asyncio
    async def test_legacy_format(self, tech_tool):
        """Legacy format returns old structure."""
        result = await tech_tool._execute(
            symbol="TEST",
            asset_type="stock",
            legacy_format=True,
        )

        # Check old-style keys
        assert "price" in result and isinstance(result["price"], (int, float))
        assert "indicators" in result
        assert "SMA_50" in result["indicators"]  # Old keys were uppercase
        assert "signals" in result
        assert all(isinstance(s, str) for s in result["signals"])  # Flat strings

    @pytest.mark.asyncio
    async def test_signals_are_structured(self, tech_tool):
        """New format returns structured signal objects."""
        result = await tech_tool._execute(
            symbol="TEST",
            asset_type="stock",
            legacy_format=False,
        )

        if result["signals"]:
            signal = result["signals"][0]
            assert "indicator" in signal
            assert "signal_type" in signal
            assert "direction" in signal
            assert "confidence" in signal

    @pytest.mark.asyncio
    async def test_risk_context(self, tech_tool):
        """Risk context includes ATR stop-losses."""
        result = await tech_tool._execute(
            symbol="TEST",
            asset_type="stock",
            legacy_format=False,
        )

        assert "risk_context" in result
        assert "atr_stop_long_2x" in result["risk_context"]
        assert "atr_stop_short_2x" in result["risk_context"]


class TestNaNHandling:
    @pytest.mark.asyncio
    async def test_nan_converted_to_none(self, tech_tool):
        """NaN values are converted to None in output."""
        result = await tech_tool._execute(
            symbol="TEST",
            asset_type="stock",
            legacy_format=False,
        )

        # Check that no NaN values exist (would fail JSON serialization)
        import json
        try:
            json.dumps(result)
        except (TypeError, ValueError) as e:
            pytest.fail(f"Output contains non-serializable values: {e}")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/technical-analysis-improvements.spec.md` for full context
2. **Check dependencies** — verify TASK-067 through TASK-071 are in `tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-074-output-restructuring.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-opus-session
**Date**: 2026-03-02
**Notes**:

Restructured `_execute()` output in `parrot/tools/technical_analysis.py`:

1. **New `legacy_format` parameter**: `_execute()` now accepts `legacy_format: bool = False`
   - `legacy_format=True`: Returns old flat structure for backward compatibility
   - `legacy_format=False` (default): Returns new nested structure

2. **New Indicator Calculations**:
   - Added SMA(20) in addition to existing SMA(50/200)
   - Added EMA(12) and EMA(26) using existing `_calculate_ema()`
   - Integrated ADX output from `_calculate_adx()`
   - Integrated ATR output from `_calculate_atr()`

3. **New Output Structure** (grouped by category):
   - `price`: {current, change_1d, change_1d_pct}
   - `indicators.trend`: {sma_20, sma_50, sma_200, ema_12, ema_26, adx}
   - `indicators.momentum`: {rsi_14: {value, zone}, macd: {line, signal, histogram, histogram_rising}}
   - `indicators.volatility`: {bollinger: {upper, middle, lower, bandwidth_pct, price_position}, atr}
   - `indicators.volume`: {current, avg_20d, ratio, is_high}
   - `signals`: List of structured signal objects (not flat strings)
   - `risk_context`: {atr_stop_long_2x, atr_stop_short_2x, volatility_annualized_pct}

4. **Helper Methods Added**:
   - `_safe_float()`: Safely convert values to float, handling NaN → None
   - `_get_rsi_zone()`: Classify RSI into zones (overbought/bullish/bearish/oversold)
   - `_calculate_bb_bandwidth()`: Calculate Bollinger Bands bandwidth percentage
   - `_get_bb_position()`: Determine price position within bands
   - `_calculate_annualized_vol()`: Calculate annualized volatility from daily returns
   - `_build_structured_output()`: Build new nested output structure
   - `_build_legacy_output()`: Build old flat output structure

Created comprehensive test suite at `tests/test_technical_analysis_output.py` with 27 tests covering:
- New output structure validation
- Legacy output compatibility
- NaN handling and JSON serializability
- All helper methods
- Integration tests for full `_execute()` flow

All 27 tests passing.

**Deviations from spec**: none
