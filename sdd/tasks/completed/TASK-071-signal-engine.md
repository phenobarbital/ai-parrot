# TASK-071: Signal Generation Engine

**Feature**: TechnicalAnalysisTool Improvements
**Spec**: `sdd/specs/technical-analysis-improvements.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-067, TASK-068, TASK-069, TASK-070
**Assigned-to**: claude-opus-session

---

## Context

The current signal system produces flat string signals like "Bullish Trend (Price > SMA200)" with no hierarchy or confidence scoring. The signal engine transforms raw indicator values into structured `TechnicalSignal` objects with:

- Signal type (golden_cross, overbought, etc.)
- Direction (bullish, bearish, neutral)
- Strength (strong, moderate, weak)
- Confidence (0.0-1.0, adjusted by confirming/conflicting signals)

Reference: Spec Section 3 (Module 2: Signal Generation Engine)

---

## Scope

- Implement `_generate_signals()` method to produce `List[TechnicalSignal]`
- Implement `_calculate_signal_confidence()` for cross-signal confirmation
- Implement full signal catalog (see table below)
- Base confidence from strength: strong=0.7, moderate=0.5, weak=0.3
- Adjust confidence based on confirming/conflicting signals

**Signal Catalog:**

| Condition | Signal Type | Direction | Strength |
|-----------|-------------|-----------|----------|
| SMA20 crosses above SMA50 | `golden_cross` | bullish | strong |
| SMA20 crosses below SMA50 | `death_cross` | bearish | strong |
| Price > SMA200 | `above_long_trend` | bullish | moderate |
| Price < SMA200 | `below_long_trend` | bearish | moderate |
| EMA12 > EMA26 | `ema_bullish_alignment` | bullish | moderate |
| EMA12 < EMA26 | `ema_bearish_alignment` | bearish | moderate |
| ADX > 25, +DI > -DI | `strong_bullish_trend` | bullish | strong |
| ADX > 25, -DI > +DI | `strong_bearish_trend` | bearish | strong |
| ADX < 20 | `trendless_market` | neutral | weak |
| RSI > 70 | `overbought` | bearish | moderate |
| RSI < 30 | `oversold` | bullish | moderate |
| RSI 50-70 | `bullish_momentum` | bullish | weak |
| RSI 30-50 | `bearish_momentum` | bearish | weak |
| MACD histogram crosses above 0 | `macd_bullish_crossover` | bullish | strong |
| MACD histogram crosses below 0 | `macd_bearish_crossover` | bearish | strong |
| Price below lower BB | `bb_oversold` | bullish | moderate |
| Price above upper BB | `bb_overbought` | bearish | moderate |
| Volume > 1.5x avg | `high_volume` | neutral | moderate |
| Volume > 2.0x avg, price up | `volume_breakout_bullish` | bullish | strong |
| Volume > 2.0x avg, price down | `volume_breakdown_bearish` | bearish | strong |

**NOT in scope**:
- CompositeScoreTool (TASK-072)
- Multi-timeframe analysis (TASK-073)
- Output restructuring (TASK-074)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/technical_analysis.py` | MODIFY | Add signal generation methods |
| `tests/test_technical_analysis_signals.py` | CREATE | Unit tests for signal generation |

---

## Implementation Notes

### Pattern to Follow

```python
def _generate_signals(
    self,
    df: pd.DataFrame,
    indicators: dict,
    adx_output: ADXOutput | None = None
) -> list[TechnicalSignal]:
    """
    Generate structured signals from indicator values.

    Args:
        df: DataFrame with price and indicator columns
        indicators: Dict of computed indicator values
        adx_output: ADXOutput if ADX was computed

    Returns:
        List of TechnicalSignal objects
    """
    signals = []
    price = float(df['close'].iloc[-1])

    # Trend signals
    if indicators.get('SMA_200'):
        if price > indicators['SMA_200']:
            signals.append(TechnicalSignal(
                indicator="SMA",
                signal_type="above_long_trend",
                direction="bullish",
                strength="moderate",
                confidence=0.5,  # Will be adjusted later
                value=indicators['SMA_200'],
                description=f"Price ${price:.2f} above SMA200 ${indicators['SMA_200']:.2f}"
            ))

    # RSI signals
    rsi = indicators.get('RSI_14')
    if rsi:
        if rsi > 70:
            signals.append(TechnicalSignal(
                indicator="RSI",
                signal_type="overbought",
                direction="bearish",
                strength="moderate",
                confidence=0.5,
                value=rsi,
                description=f"RSI {rsi:.1f} indicates overbought conditions"
            ))
        elif rsi < 30:
            signals.append(TechnicalSignal(
                indicator="RSI",
                signal_type="oversold",
                direction="bullish",
                strength="moderate",
                confidence=0.5,
                value=rsi,
                description=f"RSI {rsi:.1f} indicates oversold conditions"
            ))

    # ADX signals
    if adx_output:
        if adx_output.value > 25 and adx_output.trend_direction == "bullish":
            signals.append(TechnicalSignal(
                indicator="ADX",
                signal_type="strong_bullish_trend",
                direction="bullish",
                strength="strong",
                confidence=0.7,
                value=adx_output.value,
                description=f"ADX {adx_output.value:.1f} with +DI > -DI confirms strong bullish trend"
            ))

    # ... continue for all signal types

    # Adjust confidence based on cross-signal confirmation
    signals = self._adjust_signal_confidence(signals)

    return signals


def _calculate_signal_confidence(
    self,
    signal: TechnicalSignal,
    all_signals: list[TechnicalSignal]
) -> float:
    """
    Calculate adjusted confidence based on confirming/conflicting signals.

    Base confidence: strong=0.7, moderate=0.5, weak=0.3

    Modifiers:
    - Each confirming signal in same direction: +0.05 (max +0.20)
    - Each conflicting signal: -0.10 (min -0.20)
    - ADX > 25 in same direction: +0.10 (trend confirmation)
    - Volume confirmation: +0.10

    Final confidence clamped to [0.1, 0.95]
    """
    # Base confidence
    base = {"strong": 0.7, "moderate": 0.5, "weak": 0.3}[signal.strength]

    confirming = 0
    conflicting = 0

    for other in all_signals:
        if other is signal:
            continue
        if other.direction == signal.direction and other.direction != "neutral":
            confirming += 1
        elif other.direction != "neutral" and signal.direction != "neutral":
            if other.direction != signal.direction:
                conflicting += 1

    # Apply modifiers
    adjustment = min(confirming * 0.05, 0.20) - min(conflicting * 0.10, 0.20)

    # ADX confirmation bonus
    adx_signals = [s for s in all_signals if s.indicator == "ADX" and "strong" in s.signal_type]
    if adx_signals and adx_signals[0].direction == signal.direction:
        adjustment += 0.10

    # Volume confirmation bonus
    vol_signals = [s for s in all_signals if s.indicator == "Volume" and "breakout" in s.signal_type]
    if vol_signals and vol_signals[0].direction == signal.direction:
        adjustment += 0.10

    return max(0.1, min(0.95, base + adjustment))
```

### Key Constraints

- Signal confidence must be between 0.1 and 0.95
- Crossover signals (golden_cross, death_cross, macd_crossover) require comparing current vs previous values
- Handle missing indicators gracefully (skip signal if indicator unavailable)
- Human-readable descriptions for each signal

### References in Codebase

- `parrot/tools/technical_analysis.py` lines 224-249 — existing flat signal generation
- Brainstorm doc lines 159-255 — signal generation reference

---

## Acceptance Criteria

- [ ] `_generate_signals()` returns `List[TechnicalSignal]`
- [ ] All 20 signal types from catalog implemented
- [ ] Confidence calculation includes confirming/conflicting signal adjustment
- [ ] Crossover signals detect transitions (not just current state)
- [ ] Human-readable descriptions for each signal
- [ ] Graceful handling of missing indicators
- [ ] All tests pass: `pytest tests/test_technical_analysis_signals.py -v`

---

## Test Specification

```python
# tests/test_technical_analysis_signals.py
import pytest
import pandas as pd
import numpy as np
from parrot.tools.technical_analysis import TechnicalAnalysisTool, TechnicalSignal


@pytest.fixture
def tech_tool():
    return TechnicalAnalysisTool()


@pytest.fixture
def overbought_indicators():
    """Indicators showing overbought conditions."""
    return {
        "RSI_14": 75.0,
        "SMA_200": 180.0,
        "MACD": {"value": 2.0, "signal": 1.5, "hist": 0.5},
    }


@pytest.fixture
def bullish_df():
    """DataFrame with bullish price action."""
    np.random.seed(42)
    n = 50
    close = 100 + np.cumsum(np.abs(np.random.randn(n)))
    return pd.DataFrame({
        'close': close,
        'high': close + 1,
        'low': close - 1,
        'volume': np.random.randint(1000, 2000, n),
    })


class TestSignalGeneration:
    def test_overbought_signal(self, tech_tool, bullish_df, overbought_indicators):
        """RSI > 70 generates overbought signal."""
        signals = tech_tool._generate_signals(bullish_df, overbought_indicators)
        overbought = [s for s in signals if s.signal_type == "overbought"]
        assert len(overbought) == 1
        assert overbought[0].direction == "bearish"
        assert overbought[0].strength == "moderate"

    def test_above_long_trend_signal(self, tech_tool, bullish_df):
        """Price > SMA200 generates above_long_trend signal."""
        indicators = {"SMA_200": 50.0}  # Price ~150 is above
        bullish_df['close'] = bullish_df['close'] + 100  # Ensure above
        signals = tech_tool._generate_signals(bullish_df, indicators)
        trend = [s for s in signals if s.signal_type == "above_long_trend"]
        assert len(trend) == 1
        assert trend[0].direction == "bullish"


class TestConfidenceCalculation:
    def test_confirming_signals_increase_confidence(self, tech_tool):
        """Multiple confirming signals increase confidence."""
        signals = [
            TechnicalSignal("SMA", "above_long_trend", "bullish", "moderate", 0.5, 180, ""),
            TechnicalSignal("RSI", "bullish_momentum", "bullish", "weak", 0.3, 55, ""),
            TechnicalSignal("MACD", "macd_bullish_crossover", "bullish", "strong", 0.7, 0.5, ""),
        ]

        # After adjustment, first signal should have higher confidence
        adjusted = tech_tool._calculate_signal_confidence(signals[0], signals)
        assert adjusted > 0.5  # Base was 0.5

    def test_conflicting_signals_decrease_confidence(self, tech_tool):
        """Conflicting signals decrease confidence."""
        signals = [
            TechnicalSignal("SMA", "above_long_trend", "bullish", "moderate", 0.5, 180, ""),
            TechnicalSignal("RSI", "overbought", "bearish", "moderate", 0.5, 75, ""),
        ]

        adjusted = tech_tool._calculate_signal_confidence(signals[0], signals)
        assert adjusted < 0.5  # Base was 0.5

    def test_confidence_bounds(self, tech_tool):
        """Confidence stays within [0.1, 0.95]."""
        # Many conflicting signals
        signals = [
            TechnicalSignal("SMA", "above_long_trend", "bullish", "weak", 0.3, 180, ""),
        ] + [
            TechnicalSignal("TEST", f"signal_{i}", "bearish", "strong", 0.7, i, "")
            for i in range(10)
        ]

        adjusted = tech_tool._calculate_signal_confidence(signals[0], signals)
        assert 0.1 <= adjusted <= 0.95
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/technical-analysis-improvements.spec.md` for full context
2. **Check dependencies** — verify TASK-067, TASK-068, TASK-069, TASK-070 are in `tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-071-signal-engine.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-opus-session
**Date**: 2026-03-02
**Notes**:

Implemented full signal generation engine in `parrot/tools/technical_analysis.py`:

1. **`_generate_signals()`** (~250 lines) - Generates all 20 signal types from the catalog:
   - **Trend signals**: above_long_trend, below_long_trend, golden_cross, death_cross
   - **EMA signals**: ema_bullish_alignment, ema_bearish_alignment
   - **ADX signals**: strong_bullish_trend, strong_bearish_trend, trendless_market
   - **RSI signals**: overbought, oversold, bullish_momentum, bearish_momentum
   - **MACD signals**: macd_bullish_crossover, macd_bearish_crossover
   - **Bollinger Band signals**: bb_oversold, bb_overbought
   - **Volume signals**: high_volume, volume_breakout_bullish, volume_breakdown_bearish

2. **`_calculate_signal_confidence()`** (~50 lines) - Cross-signal confirmation:
   - Base confidence: strong=0.7, moderate=0.5, weak=0.3
   - Confirming signals: +0.05 each (max +0.20)
   - Conflicting signals: -0.10 each (max -0.20)
   - ADX confirmation bonus: +0.10
   - Volume confirmation bonus: +0.10
   - Final confidence clamped to [0.1, 0.95]

3. **`_adjust_signal_confidence()`** (~20 lines) - Applies confidence adjustment to all signals

Created comprehensive test suite at `tests/test_technical_analysis_signals.py` with 37 tests covering:
- All 20 signal types generation
- Confidence calculation with confirming/conflicting signals
- Confidence bounds enforcement
- ADX and volume confirmation bonuses
- Graceful handling of missing indicators
- Human-readable descriptions
- Crossover detection (golden cross, death cross, MACD)

All 37 tests passing.

**Deviations from spec**: none
