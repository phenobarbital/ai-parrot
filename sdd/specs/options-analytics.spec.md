# Feature Specification: Options Analytics Toolkit

**Feature ID**: FEAT-015
**Date**: 2026-03-02
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-PARROT currently has **zero options analytics capability**. The `YFinanceTool` with `action="options"` fetches raw chain data (strikes, bids, asks, volume, OI, IV), but there is no layer that:

- Prices options theoretically (Black-Scholes or alternatives)
- Calculates Greeks (delta, gamma, theta, vega, rho)
- Computes implied volatility from market prices
- Analyzes multi-leg strategies (verticals, diagonals, straddles, strangles, iron condors)
- Evaluates PMCC (Poor Man's Covered Call) suitability with scoring
- Provides probability-of-profit estimates

This toolkit fills the gap between raw market data (Layer 1 — Research Crews) and actionable investment recommendations (Layer 2 — Analyst Committee).

### Goals

- Provide a pure-computation `OptionsAnalyticsToolkit` that enriches pre-fetched option chain data with Greeks, pricing, and strategy analysis
- Implement Black-Scholes pricing engine with Greek calculations
- Implement implied volatility solver (Newton-Raphson with bisection fallback)
- Support 5 spread strategy analyzers: vertical, diagonal (PMCC), straddle, strangle, iron condor
- Add PMCC scanner with configurable scoring algorithm
- Compute probability-of-profit (POP) and expected value for all strategies
- Crypto-compatible design (works with any asset class, not equity-only)
- No data-fetching inside the toolkit — callers supply spot prices, chains, and volatility inputs

### Non-Goals (explicitly out of scope)

- Data fetching (handled by `YFinanceTool`, `AlpacaMarketsToolkit`)
- American-style option pricing via binomial tree (Phase 2 consideration)
- Full volatility surface construction (Phase 2 consideration)
- Real-time streaming Greeks updates
- Order execution (handled by `IBKRToolkit`, `AlpacaMarketsToolkit`)

---

## 2. Architectural Design

### Overview

A pure computation layer positioned between data-fetching tools and agent analysis. All functions accept numerical inputs or pre-fetched DataFrames — no IO, no external API calls.

### Component Diagram

```
Layer 1: Research Crews
    │
    ├─→ YFinanceTool.options() ─────────────────┐
    ├─→ AlpacaMarketsToolkit.get_option_chain() ┤
    └─→ DeribitToolkit.get_options() ───────────┤
                                                │
                                                ▼
    ┌──────────────────────────────────────────────────────┐
    │            OptionsAnalyticsToolkit                   │
    │  ┌────────────────────────────────────────────────┐  │
    │  │  black_scholes.py                              │  │
    │  │  - price, greeks, IV solver, batch compute     │  │
    │  └────────────────────────────────────────────────┘  │
    │  ┌────────────────────────────────────────────────┐  │
    │  │  spreads.py                                    │  │
    │  │  - vertical, diagonal, straddle, strangle, IC  │  │
    │  └────────────────────────────────────────────────┘  │
    │  ┌────────────────────────────────────────────────┐  │
    │  │  pmcc.py                                       │  │
    │  │  - PMCC scoring, candidate scanning            │  │
    │  └────────────────────────────────────────────────┘  │
    └──────────────────────────────────────────────────────┘
                                                │
                                                ▼
Layer 2: Analyst Committee
    │
    ├─→ equity_analyst (spread analysis, PMCC scanning)
    ├─→ risk_analyst (Greeks exposure, stress testing)
    └─→ sentiment_analyst (IV skew, put/call ratio)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` | extends | Base class for toolkit methods |
| `@tool_schema` | uses | Decorator for tool method definitions |
| `YFinanceTool` | consumer | Toolkit consumes chain data from YFinance |
| `AlpacaMarketsToolkit` | consumer | Toolkit consumes chain data from Alpaca |
| `ToolResult` | returns | All methods return structured dicts compatible with ToolResult |

### Data Models

```python
from dataclasses import dataclass
from typing import Optional
from pydantic import BaseModel, Field

@dataclass
class IVResult:
    """Result from implied volatility calculation."""
    iv: float
    converged: bool
    iterations: int
    method: str  # "newton_raphson" | "bisection"

@dataclass
class GreeksResult:
    """Greeks for a single option."""
    price: float
    delta: float
    gamma: float
    theta: float  # Per day (÷365)
    vega: float   # Per 1% vol move (÷100)
    rho: float    # Per 1% rate move (÷100)

@dataclass
class OptionLeg:
    """Single leg of a multi-leg strategy."""
    strike: float
    option_type: str  # "call" | "put"
    bid: float
    ask: float
    mid: float  # (bid + ask) / 2
    iv: Optional[float] = None

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

@dataclass
class PMCCScoringConfig:
    """Configuration for PMCC scoring algorithm."""
    leaps_delta_target: float = 0.80
    short_delta_target: float = 0.20
    min_leaps_days: int = 270
    short_days_range: tuple[int, int] = (7, 21)
    iv_sweet_spot: tuple[float, float] = (0.25, 0.50)
    min_annual_yield: float = 15.0
    risk_free_rate: float = 0.05
```

### New Public Interfaces

```python
class OptionsAnalyticsToolkit(AbstractToolkit):
    """
    Options pricing, Greeks, strategy analysis, and scanning.

    Pure analytical capabilities over pre-fetched option chain data.
    Does NOT fetch market data — callers supply spot prices, chains, and volatility.
    """

    name = "options_analytics_toolkit"

    # Single option Greeks
    async def compute_greeks(self, input: ComputeGreeksInput) -> dict:
        ...

    # Batch Greeks for entire chain
    async def compute_chain_greeks(
        self, chain_df: pd.DataFrame, spot: float, r: float, dte_years: float
    ) -> pd.DataFrame:
        ...

    # IV from market prices
    async def compute_implied_volatility(
        self, market_price: float, spot: float, strike: float,
        dte_days: int, option_type: str, r: float = 0.05
    ) -> dict:
        ...

    # Spread analyzers
    async def analyze_vertical_spread(self, input: AnalyzeSpreadInput) -> dict:
        ...

    async def analyze_diagonal_spread(self, ...) -> dict:
        ...

    async def analyze_straddle(self, ...) -> dict:
        ...

    async def analyze_strangle(self, ...) -> dict:
        ...

    async def analyze_iron_condor(self, ...) -> dict:
        ...

    # PMCC scanner
    async def scan_pmcc_candidates(
        self, symbols: list[str], chain_data: dict, config: PMCCScoringConfig = None
    ) -> list[dict]:
        ...

    # Risk analysis
    async def stress_test_greeks(
        self, spot: float, strike: float, dte_days: int, volatility: float,
        option_type: str, scenarios: dict
    ) -> dict:
        ...

    async def portfolio_greeks_exposure(self, positions: list[dict]) -> dict:
        ...
```

---

## 3. Module Breakdown

### Module 1: Data Models (`models.py`)

- **Path**: `parrot/tools/options/models.py`
- **Responsibility**: Shared dataclasses and Pydantic input models
- **Depends on**: None (pure definitions)

### Module 2: Black-Scholes Engine (`black_scholes.py`)

- **Path**: `parrot/tools/options/black_scholes.py`
- **Responsibility**:
  - Core BS pricing: `black_scholes_price()`, `black_scholes_greeks()`
  - Standalone Greeks: `black_scholes_delta()`, `black_scholes_vega()`
  - IV solver: `implied_volatility()` with Newton-Raphson + bisection fallback
  - IV estimation heuristic: `estimate_iv()` when market IV unavailable
  - Put-Call Parity validation: `validate_put_call_parity()`
  - Batch Greeks: `compute_chain_greeks()` vectorized with numpy
  - Probability of Profit: `probability_of_profit()`
- **Depends on**: Module 1 (models), scipy.stats, numpy, math

### Module 3: Spread Strategy Analyzer (`spreads.py`)

- **Path**: `parrot/tools/options/spreads.py`
- **Responsibility**:
  - Vertical spread analysis (bull/bear call/put): max_profit, max_loss, breakeven, POP, EV
  - Diagonal spread analysis (PMCC): net_debit, short_premium, time_decay_advantage
  - Straddle analysis: total_cost, breakeven_up/down, move_needed_pct, POP
  - Strangle analysis: total_cost, breakeven_up/down, expected_vol_vs_implied
  - Iron Condor analysis: net_credit, max_loss, profit_range, POP
  - Net Greeks aggregation for multi-leg positions
- **Depends on**: Module 1 (models), Module 2 (black_scholes)

### Module 4: PMCC Scanner (`pmcc.py`)

- **Path**: `parrot/tools/options/pmcc.py`
- **Responsibility**:
  - PMCC candidate scoring on 11-point scale (6 dimensions)
  - LEAPS selection logic (≥270 days, target delta)
  - Short leg selection (7-21 day range)
  - Yield calculation (weekly yield, annual yield estimate)
  - Batch scanning with `asyncio.gather()` + semaphore
- **Depends on**: Module 1 (models), Module 2 (black_scholes)

### Module 5: Toolkit Class (`toolkit.py`)

- **Path**: `parrot/tools/options/toolkit.py`
- **Responsibility**:
  - `OptionsAnalyticsToolkit(AbstractToolkit)` class
  - All `@tool_schema` decorated async methods
  - Error handling and result formatting
  - Integration with AI-Parrot tool system
- **Depends on**: Modules 1-4, AbstractToolkit

### Module 6: Package Init (`__init__.py`)

- **Path**: `parrot/tools/options/__init__.py`
- **Responsibility**: Export `OptionsAnalyticsToolkit` and key models
- **Depends on**: Module 5

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_bs_price_atm_call` | black_scholes | ATM call pricing matches known value |
| `test_bs_price_deep_itm` | black_scholes | Deep ITM option pricing edge case |
| `test_bs_price_deep_otm` | black_scholes | Deep OTM option pricing edge case |
| `test_bs_greeks_call` | black_scholes | All Greeks for call option |
| `test_bs_greeks_put` | black_scholes | All Greeks for put option |
| `test_iv_solver_convergence` | black_scholes | IV solver converges on known market price |
| `test_iv_solver_fallback` | black_scholes | Bisection fallback when Newton-Raphson fails |
| `test_iv_invalid_price` | black_scholes | IV solver returns None for impossible prices |
| `test_put_call_parity` | black_scholes | Validates put-call parity relationship |
| `test_batch_greeks_vectorized` | black_scholes | Batch computation matches individual |
| `test_pop_debit_spread` | black_scholes | POP calculation for debit spread |
| `test_vertical_bull_call` | spreads | Bull call spread analysis |
| `test_vertical_bear_put` | spreads | Bear put spread analysis |
| `test_diagonal_pmcc` | spreads | Diagonal PMCC analysis |
| `test_straddle_analysis` | spreads | Straddle metrics and breakevens |
| `test_strangle_analysis` | spreads | Strangle metrics and breakevens |
| `test_iron_condor` | spreads | Iron condor credit, max_loss, profit_range |
| `test_net_greeks_aggregation` | spreads | Multi-leg net Greeks |
| `test_pmcc_scoring` | pmcc | 11-point PMCC scoring algorithm |
| `test_pmcc_leaps_selection` | pmcc | LEAPS selection by delta target |
| `test_pmcc_yield_calculation` | pmcc | Annual yield estimate accuracy |
| `test_edge_t_zero` | black_scholes | T=0 edge case handling |
| `test_edge_sigma_zero` | black_scholes | sigma=0 edge case handling |
| `test_edge_negative_rates` | black_scholes | Negative interest rate handling |

### Integration Tests

| Test | Description |
|---|---|
| `test_yfinance_to_analytics` | Feed YFinanceTool chain output → OptionsAnalyticsToolkit → verify Greeks |
| `test_full_pmcc_pipeline` | Full PMCC scanning pipeline with mock chain data |
| `test_toolkit_tool_schema` | Verify all toolkit methods have valid tool schemas |
| `test_toolkit_async_methods` | All toolkit methods are properly async |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_option_chain():
    """Sample option chain DataFrame with realistic data."""
    return pd.DataFrame({
        'strike': [95.0, 100.0, 105.0, 110.0],
        'bid': [6.50, 3.20, 1.40, 0.50],
        'ask': [6.80, 3.40, 1.60, 0.70],
        'impliedVolatility': [0.28, 0.25, 0.27, 0.30],
        'volume': [100, 250, 180, 80],
        'openInterest': [500, 1200, 800, 300],
    })

@pytest.fixture
def sample_spot_data():
    return {
        'spot': 100.0,
        'risk_free_rate': 0.05,
        'dte_days': 30,
    }

@pytest.fixture
def known_bs_values():
    """Known Black-Scholes values for validation."""
    return {
        # S=100, K=100, T=1, r=0.05, sigma=0.20, call
        'atm_call_price': 10.45,  # Approximate
        'atm_call_delta': 0.6368,
        'atm_call_gamma': 0.0188,
        'atm_call_theta': -6.41,  # Annual
        'atm_call_vega': 37.52,
    }
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest tests/test_options_analytics.py -v`)
- [ ] All integration tests pass
- [ ] Black-Scholes pricing matches reference implementation within 0.01% tolerance
- [ ] IV solver converges for 99%+ of realistic market prices
- [ ] All 5 spread analyzers return complete metrics (max_profit, max_loss, breakeven, POP, EV)
- [ ] PMCC scanner scores match trading_skills reference implementation
- [ ] Batch Greeks computation is ≥10x faster than individual calls
- [ ] No yfinance or external API dependencies in the toolkit itself
- [ ] All toolkit methods have proper `@tool_schema` decorators
- [ ] Documentation: docstrings on all public functions
- [ ] No breaking changes to existing public API

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Use `AbstractToolkit` pattern from `parrot/tools/toolkit.py`
- Pure computation in `black_scholes.py`, `spreads.py`, `pmcc.py` — no IO, no async
- Only `toolkit.py` methods are async (for consistency with toolkit pattern)
- Pydantic models for all tool inputs
- Raise `ValueError` for invalid inputs in computation layer; toolkit wraps errors
- Use dataclasses for return types in computation layer
- Use numpy vectorization for batch operations

### Known Risks / Gotchas

- **Black-Scholes assumes European options** — Alpaca trades American options. BS prices may diverge from market, especially for deep ITM puts. Document this limitation; binomial tree is Phase 2.
- **IV solver may not converge** — For extreme prices (deep OTM, near expiry), IV can be undefined or unstable. Return `IVResult.converged=False` gracefully.
- **Theta sign convention** — Some systems use positive theta for time decay loss, others negative. Document our convention clearly.
- **Dividend adjustment** — BS assumes no dividends. For dividend-paying stocks, IV will be distorted. Phase 2 consideration: add dividend yield parameter.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `scipy` | existing | `norm.cdf`, `norm.pdf` for BS calculations |
| `numpy` | existing | Vectorized batch Greeks computation |
| `pandas` | existing | DataFrame handling for chain data |

No new dependencies required.

---

## 7. Open Questions

> Questions that must be resolved before or during implementation.

- [x] **Binomial Tree pricing** — Should we add as alternative to BS for American options?: Yes
- [ ] **Volatility surface** — Should `analyze_iv_skew()` compute full smile/surface across strikes/expiries? *Owner: Jesus*: Yes
- [ ] **Earnings integration** — Should PMCC scanner integrate with `FinnhubToolkit.finnhub_earnings_calendar` to exclude stocks with earnings in short leg window? *Owner: Jesus*: Yes, integrated
- [ ] **Portfolio Greeks input** — Should `portfolio_greeks_exposure()` read from Redis directly or require caller to pass positions? *Decision: Caller passes positions (pure computation principle)*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-02 | Jesus Lara | Initial draft from brainstorm |
