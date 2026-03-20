# Feature Specification: TechnicalAnalysisTool Improvements

**Feature ID**: FEAT-016
**Date**: 2026-03-02
**Author**: Claude (from brainstorm: sdd/proposals/tech-improvements.md)
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

The current `TechnicalAnalysisTool` (`parrot/tools/technical_analysis.py`) provides basic technical indicators (SMA, RSI, MACD, Bollinger Bands) but lacks critical capabilities required for autonomous trading decisions:

1. **No ADX (Average Directional Index)** — Cannot assess trend strength. The tool can say "price is above SMA200" but not "the trend is strong/weak."

2. **No ATR (Average True Range)** — Cannot measure volatility in price terms. Critical for stop-loss placement and position sizing.

3. **No EMA** — Only SMA. EMA reacts faster to recent prices and is the industry standard for trend-following.

4. **No signal interpretation layer** — Returns raw values without composing them into actionable signals. The equity and sentiment analysts must interpret RSI=72 themselves instead of receiving "overbought + MACD bearish divergence → distribution signal."

5. **No composite scoring** — No way to rank multiple assets by technical strength. Cannot answer "which of these 10 stocks has the strongest bullish setup?"

6. **No signal generation with priority/confidence** — Current signals are flat strings with no hierarchy. "Golden Cross" and "RSI slightly above 70" are reported equivalently despite vastly different significance.

7. **No cross-timeframe analysis** — Computes indicators on a single timeframe. No multi-timeframe confirmation (e.g., "daily RSI oversold + weekly trend bullish → buy dip").

### Goals

- Add ADX, ATR, and EMA indicators to complete the technical toolkit
- Implement a structured signal generation engine with confidence scoring
- Provide composite bullish/bearish scoring for asset ranking
- Enable multi-timeframe analysis with consensus verdicts
- Restructure output format from flat to semantically grouped

### Non-Goals (explicitly out of scope)

- Adding new data sources (Alpaca, CoinGecko, CryptoQuant are sufficient)
- Implementing trading execution logic (that's the execution layer's job)
- Building a full backtesting framework
- Adding `pandas_ta` dependency (manual implementation to avoid new deps)

---

## 2. Architectural Design

### Overview

Extend the existing `TechnicalAnalysisTool` with four new capabilities delivered in phases:

1. **Indicator Layer** — Add ADX, ATR, EMA computations using numpy/pandas (no new deps)
2. **Signal Engine** — Transform raw indicator values into structured `TechnicalSignal` objects with confidence scores
3. **Scoring Engine** — Compute composite bullish/bearish scores (0-10 scale) for asset ranking
4. **Multi-Timeframe Engine** — Aggregate analysis across hourly/daily/weekly with consensus logic

### Component Diagram

```
TechnicalAnalysisTool
├── Indicator Layer (Phase 1)
│   ├── _calculate_adx()     → ADX, +DI, -DI
│   ├── _calculate_atr()     → ATR, ATR%, stop levels
│   └── _calculate_ema()     → EMA(12), EMA(26)
│
├── Signal Engine (Phase 2)
│   ├── TechnicalSignal dataclass
│   ├── _generate_signals()  → List[TechnicalSignal]
│   └── _calculate_confidence()
│
├── Scoring Engine (Phase 3)
│   ├── compute_composite_score()
│   └── _score_components()  → SMA, RSI, MACD, ADX, Volume, EMA
│
└── Multi-Timeframe Engine (Phase 4)
    ├── multi_timeframe_analysis()
    └── _compute_consensus()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `TechnicalAnalysisTool` | extends | All changes are additive to existing class |
| `AlpacaMarketsToolkit` | uses | Existing data source, no changes |
| `CoingeckoToolkit` | uses | Existing data source, no changes |
| `CryptoQuantToolkit` | uses | Existing data source, no changes |
| `equity_research_crew` | consumer | Will use `compute_composite_score` for scanning |
| `risk_analyst` | consumer | Will use ATR for stop-loss calculations |
| `Secretary` | consumer | Will use ATR stop-loss for `MemoRecommendation.stop_loss` |

### Data Models

```python
from dataclasses import dataclass
from typing import Literal
from pydantic import BaseModel, Field

@dataclass
class TechnicalSignal:
    """Structured technical signal with confidence scoring."""
    indicator: str          # "RSI", "MACD", "SMA", "ADX", "BB", "Volume"
    signal_type: str        # "overbought", "golden_cross", "bullish_crossover", etc.
    direction: Literal["bullish", "bearish", "neutral"]
    strength: Literal["strong", "moderate", "weak"]
    confidence: float       # 0.0-1.0
    value: float | None     # The indicator value that triggered the signal
    description: str        # Human-readable explanation


class ADXOutput(BaseModel):
    """ADX indicator output."""
    value: float = Field(..., description="ADX value (0-100 scale)")
    plus_di: float = Field(..., description="Positive directional indicator")
    minus_di: float = Field(..., description="Negative directional indicator")
    trend_strength: Literal["absent", "weak", "strong", "extreme"]
    trend_direction: Literal["bullish", "bearish", "undefined"]


class ATROutput(BaseModel):
    """ATR indicator output with stop-loss levels."""
    value: float = Field(..., description="Absolute ATR value")
    percent: float = Field(..., description="ATR as percentage of price")
    period: int = Field(default=14)
    stop_loss_levels: dict = Field(
        ...,
        description="Stop-loss levels at 1x, 2x, 3x ATR"
    )


class CompositeScore(BaseModel):
    """Composite technical score for asset ranking."""
    symbol: str
    score: float = Field(..., ge=0, le=10)
    max_score: float = Field(default=10.0)
    label: Literal["strong_bullish", "moderate_bullish", "neutral", "moderate_bearish", "strong_bearish"]
    components: dict
    signals: list
    recommendation_hint: str
```

### New Public Interfaces

```python
class TechnicalAnalysisTool(AbstractToolkit):
    # Existing method signature preserved
    async def _execute(
        self,
        symbol: str,
        asset_type: str,
        source: str = 'alpaca',
        interval: str = '1d',
        lookback_days: int = 365,
        legacy_format: bool = False,  # NEW: backward compatibility flag
    ) -> dict:
        ...

    # NEW: Composite scoring for asset scanning
    async def compute_composite_score(
        self,
        symbol: str,
        ohlcv_data: pd.DataFrame,
        score_type: Literal["bullish", "bearish"] = "bullish",
        asset_type: Literal["stock", "crypto"] = "stock",
    ) -> CompositeScore:
        ...

    # NEW: Multi-timeframe consensus analysis
    async def multi_timeframe_analysis(
        self,
        symbol: str,
        ohlcv_daily: pd.DataFrame,
        ohlcv_weekly: pd.DataFrame | None = None,
        ohlcv_hourly: pd.DataFrame | None = None,
    ) -> dict:
        ...
```

---

## 3. Module Breakdown

### Module 1: Indicator Extensions

- **Path**: `parrot/tools/technical_analysis.py` (extend existing)
- **Responsibility**: Add ADX, ATR, EMA calculations
- **Depends on**: existing `pandas`, `numpy`

**New Methods:**
```python
def _calculate_adx(self, df: pd.DataFrame, period: int = 14) -> dict
def _calculate_atr(self, df: pd.DataFrame, period: int = 14, current_price: float = None) -> dict
def _calculate_ema(self, series: pd.Series, span: int) -> pd.Series
```

### Module 2: Signal Generation Engine

- **Path**: `parrot/tools/technical_analysis.py` (extend existing)
- **Responsibility**: Generate structured signals from indicators
- **Depends on**: Module 1

**New Methods:**
```python
def _generate_signals(self, df: pd.DataFrame, indicators: dict) -> list[TechnicalSignal]
def _calculate_signal_confidence(self, signal: TechnicalSignal, all_signals: list) -> float
```

**Signal Catalog (partial):**
| Condition | Signal Type | Direction | Strength |
|-----------|-------------|-----------|----------|
| SMA20 crosses above SMA50 | `golden_cross` | bullish | strong |
| SMA20 crosses below SMA50 | `death_cross` | bearish | strong |
| Price > SMA200 | `above_long_trend` | bullish | moderate |
| RSI > 70 | `overbought` | bearish | moderate |
| RSI < 30 | `oversold` | bullish | moderate |
| MACD histogram crosses above 0 | `macd_bullish_crossover` | bullish | strong |
| ADX > 25, +DI > -DI | `strong_bullish_trend` | bullish | strong |
| Price below lower BB | `bb_oversold` | bullish | moderate |
| Volume > 2.0x avg, price up | `volume_breakout_bullish` | bullish | strong |

### Module 3: Composite Scoring Engine

- **Path**: `parrot/tools/technical_analysis.py` (extend existing)
- **Responsibility**: Compute 0-10 bullish/bearish scores
- **Depends on**: Module 1, Module 2

**Score Components (max 10 points):**
```python
# 1. SMA Position (0-2 pts)
#    Price > SMA20: +1.0, Price > SMA50: +1.0

# 2. RSI Zone (0-1 pt)
#    50 ≤ RSI ≤ 70: +1.0, 30 ≤ RSI < 50: +0.5, RSI < 30: +0.25

# 3. MACD (0-1.5 pts)
#    MACD > signal: +1.0, Histogram rising: +0.5

# 4. ADX Trend (0-1.5 pts)
#    ADX > 25 AND +DI > -DI: +1.5, +DI > -DI but ADX < 25: +0.5

# 5. Momentum (0-2 pts)
#    period_return / 20, clamped to [-1, 2]

# 6. Volume (0-1 pt)
#    Volume > 1.5x avg on up day: +1.0, Volume > avg: +0.5

# 7. EMA Alignment (0-1 pt)
#    EMA12 > EMA26 > SMA50: +1.0, EMA12 > EMA26 only: +0.5
```

### Module 4: Multi-Timeframe Analysis

- **Path**: `parrot/tools/technical_analysis.py` (extend existing)
- **Responsibility**: Aggregate analysis across timeframes
- **Depends on**: Module 1, Module 2, Module 3

**Confidence Adjustment Logic:**
- All timeframes agree → confidence bonus (+0.15)
- Daily and weekly agree, hourly disagrees → slight reduction (-0.05)
- Daily and weekly disagree → significant reduction (-0.15)
- All disagree → low confidence (-0.25)

### Module 5: Output Restructuring

- **Path**: `parrot/tools/technical_analysis.py` (modify `_execute`)
- **Responsibility**: Transform flat output to semantically grouped structure
- **Depends on**: Module 1, Module 2, Module 3

**New Output Structure:**
```python
{
    "symbol": "AAPL",
    "asset_type": "stock",
    "timestamp": "2025-01-15T16:00:00Z",
    "price": {"current": 185.0, "change_1d": 2.30, "change_1d_pct": 1.26},
    "indicators": {
        "trend": {"sma_20": ..., "sma_50": ..., "sma_200": ..., "ema_12": ..., "ema_26": ..., "adx": {...}},
        "momentum": {"rsi_14": {...}, "macd": {...}},
        "volatility": {"bollinger": {...}, "atr": {...}},
        "volume": {"current": ..., "avg_20d": ..., "ratio": ..., "is_high": ...}
    },
    "signals": [TechnicalSignal, ...],
    "composite_score": CompositeScore,
    "risk_context": {"atr_stop_2x": ..., "volatility_annualized_pct": ..., "sharpe_ratio_3mo": ...}
}
```

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_calculate_adx_bullish` | Module 1 | ADX > 25 with +DI > -DI returns bullish |
| `test_calculate_adx_bearish` | Module 1 | ADX > 25 with -DI > +DI returns bearish |
| `test_calculate_adx_trendless` | Module 1 | ADX < 20 returns "absent" trend_strength |
| `test_calculate_atr_stop_levels` | Module 1 | Stop-loss levels at 1x, 2x, 3x ATR are correct |
| `test_calculate_ema_vs_sma` | Module 1 | EMA responds faster to recent price changes |
| `test_generate_signal_golden_cross` | Module 2 | SMA20 crossing above SMA50 triggers signal |
| `test_generate_signal_rsi_overbought` | Module 2 | RSI > 70 generates overbought signal |
| `test_signal_confidence_confirming` | Module 2 | Multiple confirming signals increase confidence |
| `test_signal_confidence_conflicting` | Module 2 | Conflicting signals decrease confidence |
| `test_composite_score_max` | Module 3 | Perfect bullish setup scores near 10 |
| `test_composite_score_min` | Module 3 | Perfect bearish setup scores near 0 |
| `test_composite_score_crypto_adjustment` | Module 3 | Crypto uses different weights than stocks |
| `test_multi_timeframe_alignment_full` | Module 4 | All timeframes agree → high confidence |
| `test_multi_timeframe_alignment_partial` | Module 4 | Mixed signals → reduced confidence |
| `test_output_legacy_format` | Module 5 | `legacy_format=True` returns old structure |
| `test_output_new_format` | Module 5 | Default returns new nested structure |

### Integration Tests

| Test | Description |
|---|---|
| `test_end_to_end_stock_analysis` | Full analysis of AAPL from Alpaca data |
| `test_end_to_end_crypto_analysis` | Full analysis of BTC from CoinGecko data |
| `test_composite_score_batch_ranking` | Rank 5 stocks by bullish score |
| `test_multi_timeframe_with_real_data` | Daily + weekly analysis with consensus |

### Test Data / Fixtures

```python
@pytest.fixture
def bullish_ohlcv_data():
    """OHLCV data simulating a bullish trend."""
    # Price rising, RSI 55-65, MACD positive, ADX > 25
    ...

@pytest.fixture
def bearish_ohlcv_data():
    """OHLCV data simulating a bearish trend."""
    # Price falling, RSI 35-45, MACD negative, ADX > 25
    ...

@pytest.fixture
def sideways_ohlcv_data():
    """OHLCV data simulating trendless market."""
    # Price flat, RSI ~50, MACD near 0, ADX < 20
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] ADX indicator returns `value`, `plus_di`, `minus_di`, `trend_strength`, `trend_direction`
- [ ] ATR indicator returns `value`, `percent`, and `stop_loss_levels` at 1x, 2x, 3x
- [ ] EMA(12) and EMA(26) are computed alongside existing SMAs
- [ ] Signal engine generates `TechnicalSignal` objects with confidence scores
- [ ] Composite score produces 0-10 scale with component breakdown
- [ ] Multi-timeframe analysis returns consensus verdict with alignment assessment
- [ ] `legacy_format=True` parameter preserves backward compatibility
- [ ] All unit tests pass (`pytest tests/test_technical_analysis.py -v`)
- [ ] Integration tests pass with real Alpaca/CoinGecko data
- [ ] No new dependencies added (only `pandas`, `numpy`)
- [ ] ADX, ATR values validated against TradingView or `pandas_ta` reference

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Use existing `_calculate_*` method pattern for new indicators
- All calculations must handle NaN values gracefully (rolling windows)
- Use `pd.Series.ewm()` for exponential moving averages (already used for MACD)
- Pydantic models for all structured output
- Comprehensive logging with `self.logger`

### Known Risks / Gotchas

- **ADX requires High/Low/Close** — Some data sources may only provide Close. Gracefully degrade to "ADX unavailable" rather than error.
- **Multi-timeframe data alignment** — Weekly bars may not align perfectly with daily. Use timestamp-based joins.
- **Crypto 24/7 data** — Crypto has no weekends; ensure calculations don't assume 5-day weeks.
- **Backward compatibility** — Existing callers of `_execute()` must get equivalent results without code changes.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pandas` | `>=2.0` | Already present — DataFrame operations |
| `numpy` | `>=1.24` | Already present — numerical calculations |

**No new dependencies required.**

---

## 7. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Should we add `pandas_ta` as an optional dependency? — *Decision: No, implement manually to avoid new deps*
- [ ] Should composite score be exposed as a separate tool (`CompositeScoreTool`) or as a method on `TechnicalAnalysisTool`? — *Owner: Tech Lead*: a new separate tool CompositeScoreTool
- [ ] What's the maximum lookback period we should support for multi-timeframe analysis? — *Owner: Product*: 1 year
- [ ] Should ATR stop-loss levels be calculated for long and short positions separately? — *Owner: Risk Team*: Yes

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-02 | Claude | Initial draft from brainstorm document |
