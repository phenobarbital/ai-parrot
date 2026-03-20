# QuantToolkit — Brainstorming Spec

## Purpose & Motivation

AI-PARROT's risk analyst crew has extensive **prompt-level responsibilities** (VaR, beta, Sharpe, drawdown, correlation, concentration risk, stress testing) but **no dedicated computation tools** to actually perform these calculations. The risk research crew's instructions say "Query assigned sources and compute risk metrics" — but there is no tool that computes them.

Currently, the risk crew depends on the LLM doing arithmetic from raw data, which is unreliable for quantitative work. The `TechnicalAnalysisTool` calculates some indicators but is designed for signal generation, not portfolio risk management.

The QuantToolkit provides the **quantitative backbone** for:
- **Risk Analyst Crew** — VaR, drawdown, beta, Sharpe, correlation matrices, stress tests
- **Risk Analyst (deliberation)** — portfolio-level risk summary for the `portfolio_risk_summary` output block
- **Equity Analyst** — fundamental scoring (Piotroski F-Score), comparative risk metrics
- **CIO/Arbiter** — portfolio constraint validation

---

## Architecture & Integration

### Position in the PARROT Stack

```
Research Crews → collect price history, financials, portfolio state
        ↓
QuantToolkit → compute risk metrics, scores, correlations
        ↓
Analyst Committee → risk analyst uses metrics in report
        ↓
CIO/Arbiter → validates portfolio stays within constraints
        ↓
Secretary → includes risk summary in InvestmentMemo
        ↓
Execution → respects risk-adjusted sizing from QuantToolkit
```

### Design Principles

1. **Pure computation** — Functions accept DataFrames, price series, or numerical inputs. No market data fetching. Callers supply data from YFinance, Alpaca, Redis, etc.

2. **Portfolio-aware** — Unlike trading_skills' single-asset `risk.py`, this toolkit understands multi-asset portfolios aligned with PARROT's `PortfolioSnapshot` and `Position` dataclasses.

3. **Directly feeds the deliberation schemas** — Output structures match the fields in `AnalystReport.portfolio_risk_summary` (VaR, max_position_weight, top_correlation_pair, risk_budget_used).

4. **Crypto + equity** — All risk metrics work with both asset classes. Crypto's 24/7 trading and higher volatility require adjusted parameters (e.g., 365-day annualization instead of 252).

---

## Module 1: Risk Metrics Engine (`parrot/tools/quant/risk_metrics.py`)

### Reference Implementation
`trading_skills/src/trading_skills/risk.py` — 95 lines, covers single-asset risk.

### What to Adopt

**Core calculations from trading_skills** (lines 22-82):
```python
# Daily returns
returns = hist["Close"].pct_change().dropna()

# Beta vs SPY
covariance = np.cov(stock_ret, spy_ret)[0, 1]
spy_variance = np.var(spy_ret)
beta = covariance / spy_variance

# VaR (parametric)
var_95 = mean_return - 1.645 * daily_vol   # 95% confidence
var_99 = mean_return - 2.326 * daily_vol   # 99% confidence

# Maximum drawdown
cumulative = (1 + returns).cumprod()
running_max = cumulative.cummax()
drawdown = (cumulative - running_max) / running_max
max_drawdown = drawdown.min()

# Sharpe ratio
excess_return = returns.mean() * 252 - risk_free_rate
sharpe = excess_return / annual_vol
```

### What to Extend Significantly

**1. Portfolio-level VaR (not just single-asset)**

trading_skills only computes VaR per symbol. We need portfolio VaR:

```python
def portfolio_var(
    returns_df: pd.DataFrame,      # Columns = asset returns
    weights: np.ndarray,            # Position weights
    confidence: float = 0.95,
    method: str = "parametric",     # "parametric" | "historical" | "monte_carlo"
    horizon_days: int = 1,
) -> dict:
    """
    Portfolio Value at Risk.
    
    - Parametric: variance-covariance method (fast, assumes normality)
    - Historical: empirical percentile of portfolio returns (no distribution assumption)  
    - Monte Carlo: simulate N paths using covariance matrix (best for non-linear portfolios)
    
    Returns:
        {"var_amount": float, "var_pct": float, "method": str, "confidence": float}
    """
```

This is critical because the risk analyst's output schema requires `var_1d_95_usd`, which is portfolio-level, not per-asset.

**2. Conditional VaR (CVaR / Expected Shortfall)**

VaR tells you "what's the worst loss at 95% confidence" but not "how bad could it get beyond that." CVaR averages the losses in the tail. More informative for the risk analyst.

```python
def conditional_var(
    returns: pd.Series | pd.DataFrame,
    weights: np.ndarray | None = None,
    confidence: float = 0.95,
) -> float:
    """Average loss beyond VaR threshold. CVaR ≥ VaR always."""
```

**3. Rolling metrics for regime detection**

The risk crew must "flag when correlations deviate >2 std from historical norm" and "volatility spikes above historical 90th percentile." This requires rolling windows:

```python
def rolling_risk_metrics(
    returns: pd.Series,
    window: int = 60,          # Trading days
    benchmark_returns: pd.Series | None = None,
) -> pd.DataFrame:
    """
    Rolling volatility, beta, Sharpe, and VaR.
    Returns DataFrame with columns: rolling_vol, rolling_beta, rolling_sharpe, rolling_var95.
    Useful for detecting regime changes.
    """
```

**4. Stress testing framework**

```python
def stress_test(
    portfolio_returns: pd.DataFrame,
    weights: np.ndarray,
    scenarios: dict[str, dict[str, float]],
) -> dict[str, dict]:
    """
    Apply historical or hypothetical stress scenarios.
    
    Example scenarios:
    {
        "covid_crash_2020": {"SPY": -0.34, "BTC": -0.50, "TLT": 0.20},
        "rate_hike_shock": {"SPY": -0.10, "BTC": -0.25, "TLT": -0.15},
        "vol_spike_2x": {"multiplier": 2.0},  # Double current vol
    }
    
    Returns: {scenario_name: {"portfolio_loss_pct": float, "worst_position": str, ...}}
    """
```

---

## Module 2: Correlation Engine (`parrot/tools/quant/correlation.py`)

### Reference Implementation
`trading_skills/src/trading_skills/correlation.py` — 39 lines, basic Pearson correlation matrix.

### What to Adopt

The basic structure: accept multiple price series, compute correlation matrix, return structured dict. (trading_skills lines 8-38)

### What to Extend

**1. Multiple correlation methods**

```python
def compute_correlation(
    price_data: dict[str, pd.Series],  # {symbol: close_prices}
    method: str = "pearson",            # "pearson" | "spearman" | "kendall"
    window: int | None = None,          # Rolling window (None = full period)
    returns_based: bool = True,         # Correlate returns, not prices
) -> dict:
```

Pearson on prices is misleading (two random walks will show spurious correlation). **Always** correlate on returns. trading_skills correlates prices directly (`price_df.corr()` on line 26) — this is a bug we should fix.

**2. Correlation regime detection**

```python
def detect_correlation_regimes(
    price_data: dict[str, pd.Series],
    short_window: int = 20,
    long_window: int = 120,
    z_threshold: float = 2.0,
) -> dict:
    """
    Compare short-term vs long-term correlations.
    Flag pairs where short_corr deviates > z_threshold std from long_corr.
    
    This directly serves the risk crew instruction:
    "Flag when correlations deviate >2 std from historical norm"
    
    Returns: {
        "regime_alerts": [{"pair": "NVDA-SPY", "short_corr": 0.85, 
                           "long_corr": 0.45, "z_score": 2.8, "alert": "convergence_spike"}],
        "correlation_matrix_short": {...},
        "correlation_matrix_long": {...},
    }
    """
```

**3. Cross-asset correlation (stocks ↔ crypto ↔ bonds)**

The risk crew explicitly monitors "cross-asset correlations (stocks-crypto, stocks-bonds, BTC-altcoins)." This requires handling different trading calendars:
- Stocks: M-F, 252 trading days/year
- Crypto: 24/7, 365 days/year
- Must align on common timestamps before computing correlation

```python
def cross_asset_correlation(
    equity_prices: dict[str, pd.Series],
    crypto_prices: dict[str, pd.Series],
    alignment: str = "daily_close",  # "daily_close" | "hourly" | "weekly"
) -> dict:
    """Handles calendar alignment automatically."""
```

---

## Module 3: Piotroski F-Score (`parrot/tools/quant/piotroski.py`)

### Reference Implementation
`trading_skills/src/trading_skills/piotroski.py` — 306 lines, complete 9-criterion implementation.

### What to Adopt (nearly verbatim)

The **entire scoring logic** (trading_skills lines 10-305). The 9 criteria are:

1. **Positive Net Income** → NI > 0
2. **Positive ROA** → NI / Total Assets > 0
3. **Positive Operating Cash Flow** → OCF > 0
4. **Cash Flow > Net Income** → OCF > NI (quality of earnings)
5. **Lower Long-Term Debt** → LT Debt decreased YoY
6. **Higher Current Ratio** → Current Ratio increased YoY
7. **No New Shares Issued** → Shares Outstanding ≤ prior year
8. **Higher Gross Margin** → Gross Margin % increased YoY
9. **Higher Asset Turnover** → Revenue / Total Assets increased YoY

The interpretation scale is sensible: 8-9 "Excellent", 6-7 "Good", 4-5 "Fair", 0-3 "Poor".

### What to Change

1. **Decouple from yfinance** — Accept financials as dicts/DataFrames instead of calling `yf.Ticker()`:

```python
async def calculate_piotroski_score(
    self,
    quarterly_financials: pd.DataFrame,  # From YFinanceTool action="financials"
    quarterly_cashflow: pd.DataFrame,
    annual_financials: pd.DataFrame,
    annual_balance_sheet: pd.DataFrame,
) -> dict:
```

2. **Add confidence score** — trading_skills adds `"data_available": bool` for criteria 5-9 (which need YoY comparison). We should compute a `data_completeness_pct` and adjust interpretation accordingly. A Piotroski score of 7/9 with only 6 criteria having data is less meaningful than 7/9 with all 9.

3. **Batch scoring** — `score_multiple(symbols_data: dict)` for scanning. The equity analyst crew scans multiple stocks.

---

## Module 4: Volatility Analytics (`parrot/tools/quant/volatility.py`)

### Not in trading_skills — New Module

PARROT's sentiment crew monitors "VIX and volatility surface changes" and the risk crew needs "realized and implied volatility for tracked assets." Currently no tool calculates these.

```python
def realized_volatility(
    returns: pd.Series,
    window: int = 20,
    annualization: int = 252,    # 252 for stocks, 365 for crypto
    method: str = "close_to_close",  # "close_to_close" | "parkinson" | "garman_klass"
) -> pd.Series:
    """
    Multiple volatility estimators:
    - Close-to-close: standard deviation of log returns
    - Parkinson: uses high-low range (more efficient)
    - Garman-Klass: uses OHLC (most efficient)
    
    Parkinson & Garman-Klass require OHLC data but give better estimates
    from fewer data points — useful for crypto where we want intraday granularity.
    """

def volatility_cone(
    returns: pd.Series,
    windows: list[int] = [10, 20, 30, 60, 90, 120],
) -> dict:
    """
    Percentile ranks of current volatility across multiple lookback windows.
    Answers: "Is current 20-day vol high or low relative to history?"
    
    Returns: {window: {"current": vol, "percentile": rank, "min": min, "max": max, "median": med}}
    
    Critical for sentiment analyst: when current vol is at 90th+ percentile,
    that's an extreme reading to flag.
    """

def iv_vs_rv_spread(
    implied_vol: float,
    realized_vol_series: pd.Series,
    window: int = 20,
) -> dict:
    """
    IV vs realized vol spread — key metric for options sentiment.
    IV >> RV means fear premium is elevated (buy signals for contrarians).
    IV << RV means complacency (sell signals).
    
    Returns: {"spread": float, "percentile": float, "regime": "fear_premium"|"complacent"|"normal"}
    """
```

---

## Module 5: The Toolkit Class (`parrot/tools/quant_toolkit.py`)

### Class Structure

```python
class QuantToolkit(AbstractToolkit):
    """
    Quantitative risk analysis, portfolio metrics, fundamental scoring.
    
    Provides computational tools for portfolio risk management,
    correlation analysis, volatility assessment, and fundamental quality scoring.
    
    Designed to be allocated to:
    - risk_analyst: VaR, beta, drawdown, Sharpe, correlation, stress testing
    - risk_research_crew: rolling metrics, regime detection
    - equity_analyst: Piotroski F-Score, comparative risk metrics
    - sentiment_analyst: volatility cone, IV/RV spread
    """
    
    name = "quant_toolkit"
```

### Tool Methods

| Method | Primary Consumer | Description |
|--------|-----------------|-------------|
| `compute_risk_metrics` | risk_analyst | VaR, beta, Sharpe, drawdown for single asset |
| `compute_portfolio_risk` | risk_analyst | Portfolio-level VaR, CVaR, net exposure |
| `compute_correlation_matrix` | risk_analyst | Multi-asset correlation with method selection |
| `detect_correlation_regimes` | risk_research_crew | Short vs long-term correlation anomalies |
| `compute_cross_asset_correlation` | risk_analyst | Equity-crypto-bond calendar-aligned correlation |
| `compute_rolling_metrics` | risk_research_crew | Rolling vol, beta, Sharpe windows |
| `stress_test_portfolio` | risk_analyst | Scenario-based stress testing |
| `calculate_piotroski_score` | equity_analyst | Piotroski F-Score (0-9) |
| `batch_piotroski_scores` | equity_analyst | F-Score for multiple stocks |
| `compute_realized_volatility` | sentiment_analyst | Multi-method historical vol |
| `compute_volatility_cone` | sentiment_analyst | Vol percentile ranks across windows |
| `compute_iv_rv_spread` | sentiment_analyst | Implied vs realized vol regime |

### Key Pydantic Input Models

```python
class PortfolioRiskInput(BaseModel):
    """Input for portfolio-level risk computation."""
    returns_data: dict[str, list[float]] = Field(
        ..., description="Dict of {symbol: [daily_returns]} for each position"
    )
    weights: list[float] = Field(
        ..., description="Position weights (sum to 1.0)"
    )
    symbols: list[str] = Field(
        ..., description="Symbol names matching returns_data keys"
    )
    confidence: float = Field(0.95, description="VaR confidence level")
    risk_free_rate: float = Field(0.04, description="Annualized risk-free rate")
    annualization_factor: int = Field(252, description="252 for stocks, 365 for crypto")

class StressTestInput(BaseModel):
    scenario_name: str
    asset_shocks: dict[str, float] = Field(
        ..., description="Dict of {symbol: shock_pct} e.g. {'SPY': -0.10, 'BTC': -0.25}"
    )
```

---

## Integration with PARROT Schemas

The QuantToolkit output directly maps to fields in `parrot/finance/schemas.py`:

| QuantToolkit Output | Schema Field | Location |
|---|---|---|
| `var_1d_95` | `PortfolioSnapshot.daily_pnl_usd` context | Used by Secretary |
| `max_drawdown` | `PortfolioSnapshot.max_drawdown_pct` | Portfolio monitoring |
| `portfolio_var` | `AnalystReport.portfolio_risk_summary.var_1d_95_usd` | Risk analyst output |
| `correlation_regime_alerts` | `AnalystReport.key_risks` entries | Risk analyst output |
| `stress_test_results` | `AnalystReport.data_points` | Risk analyst evidence |
| `piotroski_score` | `AnalystReport.recommendations[].data_points` | Equity analyst evidence |
| `vol_percentile` | `AnalystReport.recommendations[].data_points` | Sentiment analyst evidence |

---

## File Layout

```
parrot/tools/quant/
├── __init__.py              # exports QuantToolkit
├── risk_metrics.py          # VaR, CVaR, beta, Sharpe, drawdown (single + portfolio)
├── correlation.py           # Correlation matrices, regime detection, cross-asset
├── piotroski.py             # F-Score calculation
├── volatility.py            # Realized vol, vol cone, IV/RV spread
├── stress_testing.py        # Scenario-based stress tests
├── models.py                # Shared dataclasses and Pydantic models
└── toolkit.py               # QuantToolkit (AbstractToolkit subclass)
```

---

## Dependencies

- `numpy` — already in PARROT
- `pandas` — already in PARROT
- `scipy.stats` — already in PARROT (for VaR parametric, Sharpe significance tests)
- No new dependencies required.

---

## Testing Strategy

- **Risk metrics**: Validate VaR against known examples (e.g., portfolio with 60/40 SPY/AGG)
- **Correlation**: Verify Pearson vs Spearman on known datasets; test returns-based vs price-based
- **Piotroski**: Use AAPL/MSFT real financials from YFinance to compare against trading_skills' reference output
- **Volatility**: Cross-validate Garman-Klass against close-to-close on same data
- **Stress tests**: Verify that "covid crash" scenario on 60/40 portfolio produces approximately -20%
- **Edge cases**: Single-asset portfolio, all-crypto portfolio, missing data, zero-variance asset

---

## Open Questions

1. **Monte Carlo VaR** — Worth implementing in Phase 1, or defer? It's the most accurate for portfolios with options (non-linear payoffs), but it's also the most computationally expensive. Given the OptionsAnalyticsToolkit, the CIO may need this for portfolios with spreads.

2. **Risk budget framework** — The risk analyst output includes `risk_budget_used_pct`. Should the QuantToolkit define what "risk budget" means (e.g., max portfolio VaR as % of AUM, max drawdown tolerance)? Or should that be configuration in `ExecutorConstraints`?

3. **Annualization factor** — For a mixed portfolio (60% equity + 40% crypto), should we use 252 or 365? Possible approach: compute separately, then weight-average. But this introduces correlation assumptions. Needs a design decision.

4. **Integration with Redis** — The risk research crew runs on a cron schedule. Should the QuantToolkit's heavier computations (portfolio VaR, correlation regimes) be cached in Redis with TTL? The `DeliberationTrigger` could check for stale risk metrics.