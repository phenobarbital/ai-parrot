# TechnicalAnalysisTool Improvements — Brainstorming Spec

## Current State Assessment

### What Exists

`parrot/tools/technical_analysis.py` — A `TechnicalAnalysisTool` (inherits `AbstractToolkit`) that:

- Fetches OHLCV data from Alpaca (stocks), CoinGecko (crypto), or CryptoQuant
- Computes: SMA(50, 200), RSI(14), MACD(12,26,9), Bollinger Bands(20,2)
- Returns latest indicator values + basic signals ("Bullish Trend", "Overbought", "Oversold", "High Volume")
- Supports both stocks and crypto via `asset_type` parameter

### What's Missing

1. **No ADX (Average Directional Index)** — Cannot assess trend strength. The tool can say "price is above SMA200" but not "the trend is strong/weak."

2. **No ATR (Average True Range)** — Cannot measure volatility in price terms. Critical for stop-loss placement and position sizing.

3. **No EMA** — Only SMA. EMA reacts faster to recent prices and is the industry standard for trend-following.

4. **No signal interpretation layer** — Returns raw values without composing them into actionable signals. The equity and sentiment analysts must interpret RSI=72 themselves instead of receiving "overbought + MACD bearish divergence → distribution signal."

5. **No composite scoring** — No way to rank multiple assets by technical strength. Cannot answer "which of these 10 stocks has the strongest bullish setup?"

6. **No signal generation with priority/confidence** — Current signals are flat strings with no hierarchy. "Golden Cross" and "RSI slightly above 70" are reported equivalently despite vastly different significance.

7. **No cross-timeframe analysis** — Computes indicators on a single timeframe. No multi-timeframe confirmation (e.g., "daily RSI oversold + weekly trend bullish → buy dip").

### Reference Implementation Gaps

`trading_skills/src/trading_skills/technicals.py` (292 lines) and `scanner_bullish.py` (155 lines) address most of these gaps. Key implementations:

**ADX with +DI/-DI** (technicals.py lines 112-124):
```python
adx = ta.adx(df["High"], df["Low"], close, length=14)
# Returns: ADX value, +DI (positive directional indicator), -DI (negative)
# ADX > 25 = strong trend; +DI > -DI = bullish; -DI > +DI = bearish
```

**ATR** (technicals.py lines 232-239):
```python
atr = ta.atr(df["High"], df["Low"], df["Close"], length=14)
# Percentage ATR relative to price is more useful than raw ATR
atr_pct = atr.iloc[-1] / df["Close"].iloc[-1] * 100
```

**Signal generation** (technicals.py lines 159-255):
- RSI > 70 → "overbought"
- RSI < 30 → "oversold"
- MACD histogram crosses zero → "bullish_crossover" / "bearish_crossover"
- Price crosses Bollinger Band → "below_lower_band" / "above_upper_band"
- SMA20 crosses SMA50 → "golden_cross" / "death_cross"
- ADX > 25 → "strong_trend"

**Bullish composite score** (scanner_bullish.py lines 13-127):
```python
# Score components (max ~10 points):
# Price > SMA20: +1, > SMA50: +1
# RSI 50-70: +1, RSI 30-50: +0.5, RSI <30: +0.25
# MACD > signal: +1, histogram rising: +0.5
# ADX > 25 with +DI > -DI: +1.5
# Momentum bonus: period_return/20 (capped at [-1, +2])
```

---

## Proposed Changes

### Change 1: Add Missing Indicators (ADX, ATR, EMA)

#### ADX (Average Directional Index)

**Why it matters**: ADX is the only indicator that tells you *how strong* a trend is regardless of direction. Without it, the analyst crew can't distinguish between a weak drift and a powerful move. The risk analyst needs this to size positions appropriately.

**Implementation** — Add to the calculation section after MACD:

```python
# ADX (requires High, Low, Close)
if 'high' in df.columns and 'low' in df.columns:
    delta_high = df['high'].diff()
    delta_low = -df['low'].diff()
    
    plus_dm = np.where((delta_high > delta_low) & (delta_high > 0), delta_high, 0)
    minus_dm = np.where((delta_low > delta_high) & (delta_low > 0), delta_low, 0)
    
    tr = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            abs(df['high'] - df['close'].shift(1)),
            abs(df['low'] - df['close'].shift(1))
        )
    )
    
    atr_14 = pd.Series(tr).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm).ewm(alpha=1/14, min_periods=14, adjust=False).mean() / atr_14
    minus_di = 100 * pd.Series(minus_dm).ewm(alpha=1/14, min_periods=14, adjust=False).mean() / atr_14
    
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
```

**Alternative**: Use `pandas_ta` library (used by trading_skills) which provides `ta.adx()` directly. Decision: implement manually to avoid adding a dependency, but document that `pandas_ta` is a viable optimization if we want cleaner code.

**Output format**:
```python
"ADX": {
    "value": 32.5,      # 0-100 scale
    "plus_di": 28.3,     # Bullish directional indicator
    "minus_di": 15.7,    # Bearish directional indicator
    "trend_strength": "strong",  # "absent"(<20), "weak"(20-25), "strong"(25-50), "extreme"(>50)
    "trend_direction": "bullish" # "bullish" (+DI > -DI), "bearish", or "undefined" (ADX < 20)
}
```

#### ATR (Average True Range)

**Why it matters**: ATR is the foundation for volatility-adjusted stop-losses and position sizing. The execution layer places limit orders with stop-losses — ATR tells you how wide those stops should be relative to normal price movement. A 2-ATR stop avoids being stopped out by noise; a 0.5-ATR stop is too tight.

**Implementation**:

```python
# True Range
tr = np.maximum(
    df['high'] - df['low'],
    np.maximum(
        abs(df['high'] - df['close'].shift(1)),
        abs(df['low'] - df['close'].shift(1))
    )
)
atr_14 = pd.Series(tr).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
```

**Output format**:
```python
"ATR": {
    "value": 3.42,         # Absolute ATR
    "percent": 1.85,       # ATR / price * 100
    "period": 14,
    "stop_loss_levels": {
        "tight_1x": 181.58,     # price - 1*ATR
        "standard_2x": 178.16,  # price - 2*ATR  (most common)
        "wide_3x": 174.74,      # price - 3*ATR
    }
}
```

The `stop_loss_levels` directly inform the Secretary when constructing `MemoRecommendation.stop_loss`. Instead of arbitrary percentages, stop-losses become volatility-adjusted.

#### EMA (Exponential Moving Average)

**Implementation** — Add EMA(12) and EMA(26) alongside existing SMAs:

```python
df['EMA_12'] = df['close'].ewm(span=12, adjust=False).mean()
df['EMA_26'] = df['close'].ewm(span=26, adjust=False).mean()
```

**Output format**: Same as SMA but with `"EMA_12"` and `"EMA_26"` keys.

---

### Change 2: Signal Generation Engine

#### Current Problem

The existing tool produces flat signal strings:
```python
signals = []
if summary['price'] > summary['indicators']['SMA_200']:
    signals.append("Bullish Trend (Price > SMA200)")
```

This is insufficient for autonomous trading because:
- Signals have no priority/confidence score
- No distinction between confirming vs. conflicting signals
- No aggregation into a verdict
- No directional bias assessment

#### Proposed Signal Schema

Reference: trading_skills `technicals.py` generates structured signals (lines 159-255) with indicator name + signal type. We extend this with confidence and priority.

```python
@dataclass
class TechnicalSignal:
    indicator: str          # "RSI", "MACD", "SMA", "ADX", "BB", "Volume"
    signal_type: str        # "overbought", "golden_cross", "bullish_crossover", etc.
    direction: str          # "bullish", "bearish", "neutral"
    strength: str           # "strong", "moderate", "weak"
    confidence: float       # 0.0-1.0
    value: float | None     # The indicator value that triggered the signal
    description: str        # Human-readable explanation
```

#### Signal Catalog

Derived from both trading_skills and standard TA practice:

**Trend signals:**
| Condition | Signal Type | Direction | Strength |
|-----------|-----------|-----------|----------|
| SMA20 crosses above SMA50 | `golden_cross` | bullish | strong |
| SMA20 crosses below SMA50 | `death_cross` | bearish | strong |
| Price > SMA200 | `above_long_trend` | bullish | moderate |
| Price < SMA200 | `below_long_trend` | bearish | moderate |
| EMA12 > EMA26 | `ema_bullish_alignment` | bullish | moderate |
| ADX > 25, +DI > -DI | `strong_bullish_trend` | bullish | strong |
| ADX > 25, -DI > +DI | `strong_bearish_trend` | bearish | strong |
| ADX < 20 | `trendless_market` | neutral | weak |

**Momentum signals:**
| Condition | Signal Type | Direction | Strength |
|-----------|-----------|-----------|----------|
| RSI > 70 | `overbought` | bearish | moderate |
| RSI < 30 | `oversold` | bullish | moderate |
| RSI 50-70 | `bullish_momentum` | bullish | weak |
| MACD histogram crosses above 0 | `macd_bullish_crossover` | bullish | strong |
| MACD histogram crosses below 0 | `macd_bearish_crossover` | bearish | strong |
| MACD histogram rising (but still < 0) | `macd_improving` | bullish | weak |

**Volatility signals:**
| Condition | Signal Type | Direction | Strength |
|-----------|-----------|-----------|----------|
| Price below lower BB | `bb_oversold` | bullish | moderate |
| Price above upper BB | `bb_overbought` | bearish | moderate |
| BB bandwidth < 5% | `bb_squeeze` | neutral | strong |
| ATR% > 90th percentile | `high_volatility` | neutral | strong |

**Volume signals:**
| Condition | Signal Type | Direction | Strength |
|-----------|-----------|-----------|----------|
| Volume > 1.5x 20d avg | `high_volume` | confirming | moderate |
| Volume > 2.0x 20d avg, price up | `volume_breakout_bullish` | bullish | strong |
| Volume > 2.0x 20d avg, price down | `volume_breakdown_bearish` | bearish | strong |

#### Confidence Calculation

Each signal's confidence depends on confirmation from other signals:

```python
def _calculate_signal_confidence(self, signal: TechnicalSignal, all_signals: list[TechnicalSignal]) -> float:
    """
    Base confidence from signal strength: strong=0.7, moderate=0.5, weak=0.3
    
    Modifiers:
    - Each confirming signal in same direction: +0.05 (max +0.20)
    - Each conflicting signal: -0.10 (min -0.20)
    - ADX > 25 in same direction: +0.10 (trend confirmation)
    - Volume confirmation: +0.10
    
    Final confidence clamped to [0.1, 0.95]
    """
```

---

### Change 3: Composite Scoring System

#### Bullish Score

Reference: trading_skills `scanner_bullish.py` lines 13-127.

We adopt the scoring concept but improve it with weighted components and crypto support.

```python
async def compute_composite_score(
    self,
    symbol: str,
    ohlcv_data: pd.DataFrame,
    score_type: str = "bullish",  # "bullish" | "bearish" | "momentum" | "mean_reversion"
    asset_type: str = "stock",    # "stock" | "crypto"
) -> dict:
    """
    Composite technical score combining multiple indicators.
    
    Bullish Score (0-10 scale):
      SMA position:    0-2 pts  (price vs SMA20, SMA50)
      RSI zone:        0-1 pt   (50-70 bullish, 30-50 neutral)
      MACD:            0-1.5 pts (above signal + rising histogram)
      ADX/Trend:       0-1.5 pts (ADX>25 with +DI dominance)
      Momentum:        0-2 pts  (period return, capped)
      Volume:          0-1 pt   (above average volume)
      EMA alignment:   0-1 pt   (EMA12 > EMA26 > SMA50)
    
    Returns: {
        "symbol": str,
        "score": float,
        "max_score": 10,
        "percentile_label": "strong_bullish" | "moderate_bullish" | "neutral" | "bearish",
        "components": {component_name: {score, max, detail}},
        "signals": [TechnicalSignal],
        "recommendation_hint": str,  # "trending_entry", "pullback_buy", "avoid", etc.
    }
    """
```

#### Score Components (detailed breakdown)

Adapted from trading_skills' `compute_bullish_score` but extended:

```python
# 1. SMA Position (0-2 pts)
#    Price > SMA20: +1.0
#    Price > SMA50: +1.0
#    (from trading_skills lines 43-58)

# 2. RSI Zone (0-1 pt)
#    50 ≤ RSI ≤ 70: +1.0 (healthy bullish)
#    30 ≤ RSI < 50:  +0.5 (recovery zone)
#    RSI < 30:       +0.25 (oversold bounce potential)
#    RSI > 70:       +0.0 (extended, risky)
#    (from trading_skills lines 62-73)

# 3. MACD (0-1.5 pts)
#    MACD > signal line: +1.0
#    Histogram rising (hist > prev_hist): +0.5
#    (from trading_skills lines 76-88)

# 4. ADX Trend (0-1.5 pts)
#    ADX > 25 AND +DI > -DI: +1.5 (confirmed strong bullish trend)
#    +DI > -DI but ADX < 25:  +0.5 (bullish but weak trend)
#    (from trading_skills lines 90-101)

# 5. Momentum (0-2 pts)
#    period_return / 20, clamped to [-1, 2]
#    (from trading_skills lines 103-105)

# 6. Volume (0-1 pt) — NEW, not in trading_skills
#    Volume > 1.5x 20d avg on up day: +1.0
#    Volume > avg:                     +0.5

# 7. EMA Alignment (0-1 pt) — NEW, not in trading_skills
#    EMA12 > EMA26 > SMA50 (perfect bullish stack): +1.0
#    EMA12 > EMA26 only:                             +0.5
```

#### Bearish Score (mirror of bullish)

Invert all conditions. Score 0-10 where 10 = maximally bearish.

#### Crypto-specific Adjustments

When `asset_type == "crypto"`:
- Use 365-day annualization for vol calculations
- Weight momentum higher (crypto trends harder)
- Add funding rate check if available from research crew data
- Reduce SMA weight (crypto respects EMA more than SMA)

---

### Change 4: Multi-Timeframe Analysis

#### Concept

A signal is much stronger when confirmed across multiple timeframes. The equity analyst asking "is NVDA bullish?" should get a layered answer:

```python
async def multi_timeframe_analysis(
    self,
    symbol: str,
    ohlcv_daily: pd.DataFrame,
    ohlcv_weekly: pd.DataFrame | None = None,
    ohlcv_hourly: pd.DataFrame | None = None,
) -> dict:
    """
    Computes indicators and scores on each available timeframe,
    then produces a consensus verdict.
    
    Returns: {
        "timeframes": {
            "hourly": {"score": 6.5, "bias": "bullish", "signals": [...]},
            "daily": {"score": 7.2, "bias": "bullish", "signals": [...]},
            "weekly": {"score": 4.1, "bias": "neutral", "signals": [...]},
        },
        "consensus": {
            "bias": "bullish",         # weighted average of timeframe biases
            "confidence": 0.65,        # reduces when timeframes disagree
            "alignment": "partial",    # "full", "partial", "conflicting"
            "recommendation": "bullish_with_caution",  # "strong_buy", "buy", etc.
        }
    }
    """
```

**Confidence adjustment when timeframes disagree:**
- All timeframes agree → confidence bonus (+0.15)
- Daily and weekly agree, hourly disagrees → slight reduction (-0.05)
- Daily and weekly disagree → significant reduction (-0.15)
- All disagree → low confidence (-0.25)

---

### Change 5: Restructure Output Format

#### Current Output (flat)

```python
{
    "symbol": "AAPL",
    "timestamp": "2025-01-15",
    "price": 185.0,
    "indicators": {"SMA_50": 180.0, "RSI_14": 65.0, ...},
    "signals": ["Bullish Trend (Price > SMA200)"],
    "volume": 50000000,
}
```

#### Proposed Output (structured)

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
            "atr": {"value": 3.42, "percent": 1.85,
                     "stop_loss_2x": 178.16},
        },
        "volume": {
            "current": 50000000,
            "avg_20d": 35000000,
            "ratio": 1.43,
            "is_high": False,
        },
    },
    "signals": [
        {"indicator": "SMA", "type": "above_long_trend", "direction": "bullish",
         "strength": "moderate", "confidence": 0.6, "value": 185.0},
        {"indicator": "MACD", "type": "macd_bullish_crossover", "direction": "bullish",
         "strength": "strong", "confidence": 0.75, "value": 0.65},
        {"indicator": "ADX", "type": "strong_bullish_trend", "direction": "bullish",
         "strength": "strong", "confidence": 0.7, "value": 32.5},
    ],
    "composite_score": {
        "score": 7.2,
        "max_score": 10.0,
        "label": "moderate_bullish",
        "components": {
            "sma_position": {"score": 2.0, "max": 2.0},
            "rsi_zone": {"score": 1.0, "max": 1.0},
            "macd": {"score": 1.5, "max": 1.5},
            "adx_trend": {"score": 1.5, "max": 1.5},
            "momentum": {"score": 0.7, "max": 2.0},
            "volume": {"score": 0.0, "max": 1.0},
            "ema_alignment": {"score": 0.5, "max": 1.0},
        },
    },
    "risk_context": {
        "atr_stop_2x": 178.16,
        "volatility_annualized_pct": 28.5,
        "sharpe_ratio_3mo": 1.45,
    },
}
```

---

## Implementation Plan

### Phase 1: Add indicators + restructure output

1. Add ADX computation (with +DI/-DI)
2. Add ATR computation (with stop-loss levels)
3. Add EMA(12, 26)
4. Restructure output to new nested format
5. Keep backward compatibility via optional `legacy_format=True` parameter

### Phase 2: Signal generation engine

1. Implement `TechnicalSignal` dataclass
2. Build signal catalog (all conditions from table above)
3. Add confidence calculation with cross-signal confirmation
4. Replace flat string signals with structured signal objects

### Phase 3: Composite scoring

1. Port bullish score logic from trading_skills' `scanner_bullish.py`
2. Add bearish score (inverted)
3. Add volume and EMA alignment components
4. Add crypto-specific adjustments
5. Implement batch scanning via `asyncio.gather()`

### Phase 4: Multi-timeframe analysis

1. Accept multiple OHLCV DataFrames (hourly, daily, weekly)
2. Run indicators on each timeframe independently
3. Compute consensus with confidence adjustment
4. Generate alignment report

---

## Tool Allocation Matrix Update

After these changes, the TechnicalAnalysisTool allocation to research crews and analysts should be updated:

| Agent | Tools Allocated | New Capabilities Used |
|-------|----------------|----------------------|
| equity_research_crew | TechnicalAnalysisTool | composite_score for scanning |
| equity_analyst | TechnicalAnalysisTool | multi_timeframe, signals with confidence |
| crypto_analyst | TechnicalAnalysisTool | crypto-adjusted scoring, funding rate context |
| sentiment_analyst | TechnicalAnalysisTool | ADX readings (trend strength for contrarian timing) |
| risk_analyst | TechnicalAnalysisTool | ATR (stop-loss levels), volatility context |
| Secretary | TechnicalAnalysisTool | ATR stop-loss for MemoRecommendation.stop_loss |

---

## Dependencies

- Current dependencies (`pandas`, `numpy`) — sufficient for all changes
- Optional: `pandas_ta` for cleaner indicator code (trading_skills uses it)
  - Pro: single function calls for ADX, ATR, RSI, etc.
  - Con: new dependency, less control over implementation
  - Recommendation: implement manually in Phase 1, evaluate pandas_ta adoption in Phase 2

---

## Testing Strategy

- **Indicator accuracy**: Verify ADX, ATR, EMA against TradingView or pandas_ta reference values for AAPL 3-month data
- **Signal generation**: Create synthetic price series that trigger specific signals (golden cross, RSI oversold, etc.) and verify detection
- **Composite score**: Compare output against trading_skills' `compute_bullish_score` for same input data
- **Multi-timeframe**: Test conflicting timeframe scenarios (hourly bearish, daily bullish, weekly neutral)
- **Backward compatibility**: Existing callers of `TechnicalAnalysisTool._execute()` should get equivalent (not identical) results with `legacy_format=True`
- **Crypto edge cases**: 24/7 data with gaps, extreme volatility periods (>10% daily moves)