# OptionsAnalyticsToolkit — Brainstorming Spec

## Purpose & Motivation

AI-PARROT currently has **zero options analytics capability**. The `YFinanceTool` with `action="options"` fetches raw chain data (strikes, bids, asks, volume, OI, IV), but there is no layer that:

- Prices options theoretically (Black-Scholes or alternatives)
- Calculates Greeks (delta, gamma, theta, vega, rho)
- Computes implied volatility from market prices
- Analyzes multi-leg strategies (verticals, diagonals, straddles, strangles, iron condors)
- Evaluates PMCC (Poor Man's Covered Call) suitability with scoring
- Provides probability-of-profit estimates

This toolkit fills the gap between raw market data (Layer 1 — Research Crews) and actionable investment recommendations (Layer 2 — Analyst Committee). Specifically, the **equity analyst** and **sentiment analyst** need quantitative options analysis to support their recommendations, and the **risk analyst** needs Greeks exposure data for portfolio risk assessment.

---

## Architecture & Integration

### Position in the PARROT Stack

```
Layer 1: Research Crews → collect raw option chains (YFinanceTool, AlpacaMarketsToolkit)
                ↓
Layer 1.5: OptionsAnalyticsToolkit → enrich with Greeks, pricing, strategy analysis
                ↓
Layer 2: Analyst Committee → use enriched data for recommendations
                ↓
Layer 3: Deliberation → CIO validates option-based recommendations
                ↓
Layer 5: Execution → Alpaca/IBKR execute the orders
```

### Design Principles

1. **Pure computation layer** — This toolkit does NOT fetch data. It receives pre-fetched data (from `YFinanceTool`, `AlpacaMarketsToolkit`, or data stored in Redis by research crews) and returns enriched analytics. This is a deliberate departure from trading_skills' approach where every function calls `yf.Ticker()` internally.

2. **Follows AbstractToolkit pattern** — Uses `@tool_schema` decorators with Pydantic input models, async methods, returns structured dicts compatible with `ToolResult`.

3. **No yfinance dependency** — All functions accept numerical inputs (spot price, strike, volatility, etc.) or pre-fetched DataFrames. The toolkit's caller is responsible for data sourcing.

4. **Crypto-compatible** — Options exist on crypto (Deribit, Binance Options). The pricing engine must work with any asset class — no equity-only assumptions.

---

## Module 1: Black-Scholes Engine (`parrot/tools/options/black_scholes.py`)

### Reference Implementation
`trading_skills/src/trading_skills/black_scholes.py` — 204 lines, clean implementation using only `math` + `scipy.stats.norm`.

### What to Adopt (with modifications)

**Core pricing functions:**
- `black_scholes_price(S, K, T, r, sigma, option_type)` → float
- `black_scholes_greeks(S, K, T, r, sigma, option_type)` → dict with price, delta, gamma, theta, vega, rho
- `black_scholes_delta(S, K, T, r, sigma, option_type)` → float (standalone, used frequently)
- `black_scholes_vega(S, K, T, r, sigma)` → float (standalone, needed for IV solver)

**Implied Volatility solver:**
- `implied_volatility(market_price, S, K, T, r, option_type)` → float | None
- Uses Newton-Raphson with bisection fallback (trading_skills lines 121-184)
- Modification: add `initial_guess` parameter (trading_skills hardcodes `sigma = 0.3`)
- Modification: return a result object with `{iv, converged, iterations, method}` instead of bare float

**IV estimation heuristic:**
- `estimate_iv(spot, strike, dte_years, option_type)` → float
- Rough moneyness-based approximation when market IV is unavailable (trading_skills lines 187-203)
- Modification: accept optional `historical_vol` parameter as a better base than hardcoded 0.35

### What to Add (not in trading_skills)

1. **Put-Call Parity validation** — `validate_put_call_parity(call_price, put_price, S, K, T, r)` → dict with theoretical vs. market spread, arbitrage flag. Useful for the risk analyst to detect mispriced options.

2. **Batch Greeks computation** — `compute_chain_greeks(chain_df, spot, r, dte_years)` → DataFrame with Greeks columns appended. The equity research crew fetches entire chains; computing Greeks row-by-row in a loop is wasteful. This function vectorizes the calculation using numpy.

3. **Greeks sensitivity / what-if** — `greeks_sensitivity(S, K, T, r, sigma, option_type, scenarios)` → dict mapping scenario names to Greeks. Example: "what happens to delta if vol increases 5%?". Useful for the risk analyst's stress testing.

4. **Probability of Profit (POP)** — `probability_of_profit(strategy_legs, spot, sigma, T, r)` → float. Based on lognormal distribution. Critical for the sentiment/risk analysts to evaluate whether a strategy is worth the risk.

### Implementation Notes

```python
# File: parrot/tools/options/black_scholes.py
# Dependencies: math, numpy, scipy.stats (already in PARROT deps)
# No IO, no async — pure computation functions
# These are NOT toolkit methods — they are utility functions used by the toolkit

from scipy.stats import norm
import math
import numpy as np
from typing import Optional
from dataclasses import dataclass

@dataclass
class IVResult:
    iv: float
    converged: bool
    iterations: int
    method: str  # "newton_raphson" | "bisection"

@dataclass  
class GreeksResult:
    price: float
    delta: float
    gamma: float
    theta: float  # Per day (÷365)
    vega: float   # Per 1% vol move (÷100)
    rho: float    # Per 1% rate move (÷100)
```

Key difference from trading_skills: their `black_scholes_greeks` returns a dict with `{"error": ...}` on invalid inputs. We should raise `ValueError` instead and let the toolkit method handle error wrapping — keeps the computation layer clean.

---

## Module 2: Spread Strategy Analyzer (`parrot/tools/options/spreads.py`)

### Reference Implementation
`trading_skills/src/trading_skills/spreads.py` — 270 lines, covers 5 spread types.

### Strategy Coverage

Each analyzer receives pre-fetched option data and returns structured analysis:

| Strategy | Function | Key Outputs |
|----------|----------|-------------|
| Vertical (bull/bear call/put) | `analyze_vertical()` | max_profit, max_loss, breakeven, risk_reward, POP |
| Diagonal (PMCC, calendar-like) | `analyze_diagonal()` | net_debit, short_premium, time_decay_advantage |
| Straddle | `analyze_straddle()` | total_cost, breakeven_up/down, move_needed_pct |
| Strangle | `analyze_strangle()` | total_cost, breakeven_up/down, expected_vol_vs_implied |
| Iron Condor | `analyze_iron_condor()` | net_credit, max_loss, profit_range, POP |

### What to Adopt from trading_skills

The **mathematical logic** for all 5 strategies is correct and well-structured in trading_skills. Key formulas to preserve:

**Vertical spread** (trading_skills `spreads.py` lines 32-89):
```python
# Bull call: max_profit = width - net_debit, max_loss = net_debit
# Bear call (credit): max_profit = credit, max_loss = width - credit  
# Breakeven calculation depends on direction
```

**Iron condor** (trading_skills `spreads.py` lines 226-269):
```python
# net_credit = (put_sell.mid + call_sell.mid) - (put_buy.mid + call_buy.mid)
# max_loss = max(put_width, call_width) - net_credit
# profit_range = [put_short, call_short]
```

### What to Change

1. **Decouple from yfinance** — trading_skills calls `yf.Ticker(symbol)` and `ticker.option_chain(expiry)` inside each function. We remove all data fetching. Input becomes:

```python
@dataclass
class OptionLeg:
    strike: float
    option_type: str  # "call" | "put"
    bid: float
    ask: float
    mid: float  # (bid + ask) / 2, or lastPrice fallback
    iv: Optional[float] = None
    
async def analyze_vertical(
    self,
    underlying_price: float,
    long_leg: OptionLeg,
    short_leg: OptionLeg,
    option_type: str,
    expiry_days: int,
) -> dict:
```

2. **Add Probability of Profit (POP)** — trading_skills doesn't calculate POP. For each strategy, add:
```python
# For debit spreads: POP = P(price > breakeven at expiry)
# Using lognormal: POP = 1 - norm.cdf(log(breakeven/spot) / (sigma * sqrt(T)))
# For credit spreads: POP = P(price stays within profit zone)
```

3. **Add expected value calculation** — `expected_value = POP * max_profit - (1-POP) * max_loss`. This is the single most useful number for the autonomous trading system.

4. **Greeks aggregation** — For multi-leg strategies, compute net Greeks (position delta, gamma, theta, vega). Trading_skills completely ignores portfolio Greeks.

### Integration with Execution Layer

The spread analyzer output should be directly parseable by the execution layer. Map outputs to `MemoRecommendation` schema fields:
- `entry_price_limit` → from net_debit/net_credit
- `stop_loss` → from max_loss threshold
- `take_profit` → from max_profit target (e.g., 50% of max_profit for credit spreads)

---

## Module 3: PMCC Scanner (`parrot/tools/options/pmcc_scanner.py`)

### Reference Implementation
`trading_skills/src/trading_skills/scanner_pmcc.py` — 302 lines, sophisticated scoring system.

### What to Adopt

The **scoring algorithm** (trading_skills lines 212-256) is the most valuable piece. It scores PMCC candidates on an 11-point scale across 6 dimensions:

| Criterion | Points | Condition |
|-----------|--------|-----------|
| LEAPS delta accuracy | 0-2 | Within ±0.05 of target delta → 2, ±0.10 → 1 |
| Short delta accuracy | 0-1 | Within ±0.05 → 1, ±0.10 → 0.5 |
| LEAPS liquidity | 0-1 | volume+OI > 100 → 1, > 20 → 0.5 |
| Short liquidity | 0-1 | volume+OI > 500 → 1, > 100 → 0.5 |
| LEAPS spread tightness | 0-1 | spread% < 5% → 1, < 10% → 0.5 |
| Short spread tightness | 0-1 | spread% < 10% → 1, < 20% → 0.5 |
| IV level (sweet spot) | 0-2 | 25-50% → 2, 20-60% → 1 |
| Annual yield estimate | 0-2 | > 50% → 2, > 30% → 1, > 15% → 0.5 |

The **LEAPS selection logic** (trading_skills lines 97-156) correctly:
- Finds the first expiry ≥ 270 days out (configurable `min_leaps_days`)
- Selects short-term expiry within 7-21 day range, with 5-30 day fallback
- Uses `find_strike_by_delta()` with Black-Scholes to find optimal strikes

The **yield calculation** (trading_skills lines 194-202):
```python
weekly_yield = short_mid / leaps_mid * 100
annual_yield_est = weekly_yield * (365 / short_days)
# Max profit estimation using BS pricing at short expiry
remaining_T = (leaps_days - short_days) / 365
leaps_value_at_short_expiry = black_scholes_price(
    S=short_strike, K=leaps_strike, T=remaining_T, r=0.05, sigma=avg_iv, option_type="call"
)
max_profit = leaps_value_at_short_expiry + short_mid - leaps_mid
```

### What to Change

1. **Decouple data fetching** — Accept pre-fetched chain DataFrames and expiration lists instead of calling yfinance.

2. **Make scoring weights configurable** — Hardcoded thresholds in trading_skills should become parameters:
```python
@dataclass
class PMCCScoringConfig:
    leaps_delta_target: float = 0.80
    short_delta_target: float = 0.20
    min_leaps_days: int = 270
    short_days_range: tuple[int, int] = (7, 21)
    iv_sweet_spot: tuple[float, float] = (0.25, 0.50)
    min_annual_yield: float = 15.0
    risk_free_rate: float = 0.05
```

3. **Add risk-adjusted scoring** — Factor in the underlying's beta and correlation to SPY. A PMCC on a high-beta stock during high-correlation regime is riskier than the raw yield suggests. The risk analyst crew can use this.

4. **Batch scanning** — trading_skills' `scan_symbols()` uses `ThreadPoolExecutor`. In PARROT's async architecture, use `asyncio.gather()` with semaphore for concurrency control.

---

## Module 4: The Toolkit Class (`parrot/tools/options_analytics.py`)

### Class Structure

```python
class OptionsAnalyticsToolkit(AbstractToolkit):
    """
    Options pricing, Greeks, strategy analysis, and scanning.
    
    This toolkit provides pure analytical capabilities over pre-fetched
    option chain data. It does NOT fetch market data — callers supply
    spot prices, chains, and volatility inputs.
    
    Designed to be allocated to:
    - equity_analyst: spread analysis, PMCC scanning
    - risk_analyst: Greeks exposure, POP calculations, stress testing
    - sentiment_analyst: put/call ratio analysis, IV skew signals
    """
    
    name = "options_analytics_toolkit"
```

### Tool Methods (exposed to agents via @tool_schema)

| Method | Primary Consumer | Description |
|--------|-----------------|-------------|
| `compute_greeks` | risk_analyst, equity_analyst | Single option Greeks |
| `compute_chain_greeks` | equity_analyst | Batch Greeks for entire chain |
| `compute_implied_volatility` | sentiment_analyst | IV from market prices |
| `analyze_iv_skew` | sentiment_analyst | Put vs. call IV skew analysis |
| `analyze_vertical_spread` | equity_analyst | Vertical spread analysis + POP |
| `analyze_diagonal_spread` | equity_analyst | PMCC / diagonal analysis |
| `analyze_straddle` | sentiment_analyst | Straddle analysis + POP |
| `analyze_strangle` | sentiment_analyst | Strangle analysis + POP |
| `analyze_iron_condor` | equity_analyst | Iron condor analysis + POP |
| `scan_pmcc_candidates` | equity_analyst | Batch PMCC suitability scoring |
| `stress_test_greeks` | risk_analyst | Greeks under multiple scenarios |
| `portfolio_greeks_exposure` | risk_analyst | Aggregate net Greeks across positions |

### Pydantic Input Models

```python
class ComputeGreeksInput(BaseModel):
    spot: float = Field(..., description="Current underlying price")
    strike: float = Field(..., description="Option strike price")
    dte_days: int = Field(..., description="Days to expiration")
    volatility: float = Field(..., description="Annualized IV (e.g. 0.30 for 30%)")
    option_type: str = Field(..., description="'call' or 'put'")
    risk_free_rate: float = Field(0.05, description="Risk-free rate (annualized)")

class AnalyzeSpreadInput(BaseModel):
    underlying_price: float
    long_strike: float
    long_bid: float
    long_ask: float
    short_strike: float
    short_bid: float
    short_ask: float
    option_type: str
    expiry_days: int
    volatility: float
    risk_free_rate: float = 0.05
```

---

## File Layout

```
parrot/tools/options/
├── __init__.py           # exports OptionsAnalyticsToolkit
├── black_scholes.py      # Pure BS engine (no IO, no async)
├── spreads.py            # Strategy analysis functions (pure computation)
├── pmcc.py               # PMCC scoring logic (pure computation)
├── models.py             # Shared dataclasses (OptionLeg, GreeksResult, IVResult, etc.)
└── toolkit.py            # OptionsAnalyticsToolkit (AbstractToolkit subclass)
```

---

## Dependencies

- `scipy` — already in PARROT (for `norm.cdf`, `norm.pdf`)
- `numpy` — already in PARROT (for vectorized chain Greeks)
- `math` — stdlib
- No new dependencies required.

---

## Testing Strategy

- Unit tests for BS pricing against known values (ATM options, deep ITM/OTM edge cases)
- Unit tests for IV solver convergence (test with real-world IV examples)
- Integration tests: feed YFinanceTool chain output → OptionsAnalyticsToolkit → verify Greeks
- Regression tests: compare outputs against trading_skills' reference implementation
- Edge cases: T=0, sigma=0, deep ITM/OTM, negative rates

---

## Open Questions

1. Should we add **Binomial Tree pricing** as an alternative to BS for American-style options? (Alpaca trades American options; BS is European only.) Could be a Phase 2 addition.

2. Should `analyze_iv_skew()` compute the **volatility smile/surface** across multiple strikes and expiries? This would be very valuable for the sentiment analyst but is not in trading_skills.

3. For the PMCC scanner, should we integrate with the **earnings calendar** (from `FinnhubToolkit.finnhub_earnings_calendar`) to automatically exclude/flag stocks with earnings within the short leg's expiry window? trading_skills does this with `get_next_earnings_date()` — worth replicating.

4. The `portfolio_greeks_exposure()` tool needs the current portfolio state from `PortfolioSnapshot`. Should it read from Redis directly, or should the caller pass it in? Given the "no IO in pure computation" principle, the caller should pass it.