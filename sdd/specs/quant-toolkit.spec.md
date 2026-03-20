# Feature Specification: QuantToolkit

**Feature ID**: FEAT-017
**Date**: 2026-03-02
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot's risk analyst crew has extensive **prompt-level responsibilities** (VaR, beta, Sharpe, drawdown, correlation, concentration risk, stress testing) but **no dedicated computation tools** to actually perform these calculations. The risk research crew's instructions say "Query assigned sources and compute risk metrics" — but there is no tool that computes them.

Currently, the risk crew depends on the LLM doing arithmetic from raw data, which is unreliable for quantitative work. The `TechnicalAnalysisTool` calculates some indicators but is designed for signal generation, not portfolio risk management.

The QuantToolkit provides the **quantitative backbone** for:
- **Risk Analyst Crew** — VaR, drawdown, beta, Sharpe, correlation, stress testing
- **Risk Analyst (deliberation)** — portfolio-level risk summary for the `portfolio_risk_summary` output block
- **Equity Analyst** — fundamental scoring (Piotroski F-Score), comparative risk metrics
- **CIO/Arbiter** — portfolio constraint validation
- **Sentiment Analyst** — volatility cone, IV/RV spread analysis

### Goals
- Provide a comprehensive `QuantToolkit` exposing risk and quant metrics as agent tools
- **Pure computation** — functions accept DataFrames/price series, no market data fetching
- **Portfolio-aware** — understand multi-asset portfolios aligned with `PortfolioSnapshot` and `Position` dataclasses
- **Directly feed deliberation schemas** — output matches fields in `AnalystReport.portfolio_risk_summary`
- **Crypto + equity** — all metrics work with both asset classes (24/7 vs 252-day annualization)
- **No new dependencies** — use only numpy, pandas, scipy (already in project)

### Non-Goals (explicitly out of scope)
- Market data fetching (callers supply data from YFinance, Alpaca, Redis, etc.)
- Options pricing models (covered by OptionsAnalyticsToolkit if needed)
- Backtesting engine
- Real-time streaming calculations
- Machine learning-based predictions

---

## 2. Architectural Design

### Overview

The QuantToolkit follows the `AbstractToolkit` pattern. It exposes quantitative functions as tools that agents can invoke. The toolkit is **stateless** — all required data (price series, portfolio weights, financials) is passed as input parameters. This enables caching at the caller level and keeps the toolkit simple.

### Component Diagram
```
Research Crews → collect price history, financials, portfolio state
        ↓
QuantToolkit → compute risk metrics, scores, correlations
        │
        ├── risk_metrics.py   → VaR, CVaR, beta, Sharpe, drawdown
        ├── correlation.py    → correlation matrices, regime detection
        ├── piotroski.py      → F-Score (0-9) fundamental scoring
        ├── volatility.py     → realized vol, vol cone, IV/RV spread
        ├── stress_testing.py → scenario-based portfolio stress tests
        └── models.py         → shared Pydantic input/output models
        ↓
Analyst Committee → risk analyst uses metrics in AnalystReport
        ↓
CIO/Arbiter → validates portfolio stays within constraints
        ↓
Secretary → includes risk summary in InvestmentMemo
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` | extends | `QuantToolkit` inherits from `AbstractToolkit` |
| `ToolkitTool` | uses | Each computation is wrapped as a `ToolkitTool` |
| `PortfolioSnapshot` | consumes | Portfolio state from `parrot/finance/schemas.py` |
| `AnalystReport` | produces for | Output maps to `key_risks`, `data_points` fields |
| `ExecutorConstraints` | informs | Risk metrics can validate constraint thresholds |
| `Agent` | consumed by | Agents use `QuantToolkit.get_tools()` in their tool list |

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Literal
from decimal import Decimal

class PortfolioRiskInput(BaseModel):
    """Input for portfolio-level risk computation."""
    returns_data: dict[str, list[float]] = Field(
        ..., description="Dict of {symbol: [daily_returns]} for each position"
    )
    weights: list[float] = Field(
        ..., description="Position weights (must sum to 1.0)"
    )
    symbols: list[str] = Field(
        ..., description="Symbol names matching returns_data keys"
    )
    confidence: float = Field(0.95, description="VaR confidence level")
    risk_free_rate: float = Field(0.04, description="Annualized risk-free rate")
    annualization_factor: int = Field(252, description="252 for stocks, 365 for crypto")

class AssetRiskInput(BaseModel):
    """Input for single-asset risk metrics."""
    returns: list[float] = Field(..., description="Daily return series")
    benchmark_returns: list[float] | None = Field(None, description="Benchmark returns for beta")
    risk_free_rate: float = Field(0.04, description="Annualized risk-free rate")
    annualization_factor: int = Field(252, description="Trading days per year")

class CorrelationInput(BaseModel):
    """Input for correlation analysis."""
    price_data: dict[str, list[float]] = Field(
        ..., description="Dict of {symbol: [close_prices]}"
    )
    method: Literal["pearson", "spearman", "kendall"] = Field("pearson")
    returns_based: bool = Field(True, description="Correlate returns, not prices")

class StressScenario(BaseModel):
    """A single stress test scenario."""
    name: str = Field(..., description="Scenario name, e.g., 'covid_crash_2020'")
    asset_shocks: dict[str, float] = Field(
        ..., description="Dict of {symbol: shock_pct} e.g., {'SPY': -0.10}"
    )

class PiotroskiInput(BaseModel):
    """Input for Piotroski F-Score calculation."""
    quarterly_financials: dict[str, float] = Field(
        ..., description="Current quarter financials"
    )
    prior_year_financials: dict[str, float] = Field(
        ..., description="Prior year financials for YoY comparison"
    )

class RiskMetricsOutput(BaseModel):
    """Output from single-asset risk calculation."""
    volatility_annual: float
    beta: float | None
    sharpe_ratio: float
    max_drawdown: float
    var_95: float
    var_99: float
    cvar_95: float

class PortfolioRiskOutput(BaseModel):
    """Output from portfolio risk calculation."""
    var_1d_95_usd: float
    var_1d_99_usd: float
    cvar_1d_95_usd: float
    portfolio_volatility: float
    portfolio_beta: float | None
    portfolio_sharpe: float
    max_drawdown: float
    net_exposure: float
    gross_exposure: float
```

### New Public Interfaces

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

    # Risk Metrics
    async def compute_risk_metrics(
        self, input_data: AssetRiskInput
    ) -> RiskMetricsOutput:
        """Compute VaR, beta, Sharpe, drawdown for a single asset."""

    async def compute_portfolio_risk(
        self, input_data: PortfolioRiskInput
    ) -> PortfolioRiskOutput:
        """Compute portfolio-level VaR, CVaR, beta, Sharpe, net/gross exposure."""

    async def compute_rolling_metrics(
        self,
        returns: list[float],
        window: int = 60,
        benchmark_returns: list[float] | None = None,
    ) -> dict:
        """Rolling volatility, beta, Sharpe, VaR for regime detection."""

    # Correlation
    async def compute_correlation_matrix(
        self, input_data: CorrelationInput
    ) -> dict:
        """Multi-asset correlation with method selection."""

    async def detect_correlation_regimes(
        self,
        price_data: dict[str, list[float]],
        short_window: int = 20,
        long_window: int = 120,
        z_threshold: float = 2.0,
    ) -> dict:
        """Flag pairs where short-term correlation deviates >z_threshold from long-term."""

    async def compute_cross_asset_correlation(
        self,
        equity_prices: dict[str, list[float]],
        crypto_prices: dict[str, list[float]],
        timestamps_equity: list[str],
        timestamps_crypto: list[str],
    ) -> dict:
        """Calendar-aligned correlation between equities and crypto."""

    # Stress Testing
    async def stress_test_portfolio(
        self,
        portfolio_returns: dict[str, list[float]],
        weights: list[float],
        scenarios: list[StressScenario],
    ) -> dict:
        """Apply historical or hypothetical stress scenarios."""

    # Piotroski F-Score
    async def calculate_piotroski_score(
        self, input_data: PiotroskiInput
    ) -> dict:
        """Calculate Piotroski F-Score (0-9) for fundamental quality."""

    async def batch_piotroski_scores(
        self, symbols_data: dict[str, PiotroskiInput]
    ) -> dict:
        """F-Score for multiple stocks."""

    # Volatility
    async def compute_realized_volatility(
        self,
        returns: list[float],
        window: int = 20,
        annualization: int = 252,
        method: str = "close_to_close",
    ) -> list[float]:
        """Rolling realized volatility with multiple estimators."""

    async def compute_volatility_cone(
        self,
        returns: list[float],
        windows: list[int] = [10, 20, 30, 60, 90, 120],
    ) -> dict:
        """Percentile ranks of current vol across multiple lookback windows."""

    async def compute_iv_rv_spread(
        self,
        implied_vol: float,
        realized_vol_series: list[float],
        window: int = 20,
    ) -> dict:
        """IV vs realized vol spread for options sentiment."""
```

---

## 3. Module Breakdown

### Module 1: Data Models
- **Path**: `parrot/tools/quant/models.py`
- **Responsibility**: All Pydantic input/output models (PortfolioRiskInput, AssetRiskInput, CorrelationInput, StressScenario, PiotroskiInput, RiskMetricsOutput, PortfolioRiskOutput)
- **Depends on**: None

### Module 2: Risk Metrics Engine
- **Path**: `parrot/tools/quant/risk_metrics.py`
- **Responsibility**:
  - Single-asset: daily returns, beta vs benchmark, VaR (parametric), CVaR, maximum drawdown, Sharpe ratio
  - Portfolio-level: portfolio VaR (parametric, historical, monte_carlo options), portfolio CVaR, portfolio beta/Sharpe
  - Rolling: rolling volatility, rolling beta, rolling Sharpe, rolling VaR
- **Depends on**: Module 1

### Module 3: Correlation Engine
- **Path**: `parrot/tools/quant/correlation.py`
- **Responsibility**:
  - Correlation matrices (Pearson, Spearman, Kendall) on **returns** (not prices)
  - Correlation regime detection (short vs long window, z-score alerts)
  - Cross-asset correlation with calendar alignment (equity 252-day vs crypto 365-day)
- **Depends on**: Module 1

### Module 4: Piotroski F-Score
- **Path**: `parrot/tools/quant/piotroski.py`
- **Responsibility**:
  - 9-criterion F-Score calculation (profitability, leverage, operating efficiency)
  - Data completeness scoring (how many of the 9 criteria have data)
  - Batch scoring for multiple symbols
  - Interpretation scale (8-9 Excellent, 6-7 Good, 4-5 Fair, 0-3 Poor)
- **Depends on**: Module 1

### Module 5: Volatility Analytics
- **Path**: `parrot/tools/quant/volatility.py`
- **Responsibility**:
  - Realized volatility estimators (close-to-close, Parkinson high-low, Garman-Klass OHLC)
  - Volatility cone (percentile ranks across multiple windows)
  - IV vs RV spread (implied vol vs realized vol regime detection)
- **Depends on**: Module 1

### Module 6: Stress Testing
- **Path**: `parrot/tools/quant/stress_testing.py`
- **Responsibility**:
  - Apply predefined scenarios (covid_crash_2020, rate_hike_shock, etc.)
  - Custom scenario application
  - Portfolio loss calculation per scenario
  - Worst-position identification
- **Depends on**: Module 1, Module 2

### Module 7: QuantToolkit (Main Toolkit)
- **Path**: `parrot/tools/quant/__init__.py`
- **Responsibility**: The `QuantToolkit` class inheriting `AbstractToolkit`. Exposes all methods as tools via `get_tools()`. Orchestrates calls to underlying modules.
- **Depends on**: Modules 1-6

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_models_validation` | Module 1 | Validates all Pydantic models with valid/invalid data |
| `test_portfolio_risk_input_weights_sum` | Module 1 | Weights must sum to ~1.0 |
| `test_var_parametric` | Module 2 | VaR calculation against known example |
| `test_cvar_greater_than_var` | Module 2 | CVaR >= VaR always |
| `test_beta_calculation` | Module 2 | Beta vs benchmark matches manual calculation |
| `test_sharpe_ratio` | Module 2 | Sharpe with known risk-free rate |
| `test_max_drawdown` | Module 2 | Max drawdown on known price series |
| `test_portfolio_var_parametric` | Module 2 | Portfolio VaR with covariance method |
| `test_portfolio_var_historical` | Module 2 | Portfolio VaR with empirical percentile |
| `test_rolling_metrics_window` | Module 2 | Rolling window produces correct length |
| `test_correlation_pearson` | Module 3 | Pearson correlation on known dataset |
| `test_correlation_spearman` | Module 3 | Spearman correlation differs from Pearson |
| `test_correlation_returns_vs_prices` | Module 3 | Returns-based correlation is different from price-based |
| `test_regime_detection_alert` | Module 3 | Detects short vs long correlation deviation |
| `test_cross_asset_alignment` | Module 3 | Calendar alignment between equity and crypto |
| `test_piotroski_all_criteria` | Module 4 | Full 9-criterion score with complete data |
| `test_piotroski_partial_data` | Module 4 | Handles missing criteria gracefully |
| `test_piotroski_interpretation` | Module 4 | Interpretation scale matches score |
| `test_batch_piotroski` | Module 4 | Multiple symbols scored correctly |
| `test_realized_vol_close_to_close` | Module 5 | Standard vol estimator |
| `test_realized_vol_parkinson` | Module 5 | Parkinson estimator with high-low data |
| `test_vol_cone_percentiles` | Module 5 | Percentile ranks are within 0-100 |
| `test_iv_rv_spread_regimes` | Module 5 | Correct regime classification |
| `test_stress_test_covid` | Module 6 | Covid crash scenario produces expected loss |
| `test_stress_test_worst_position` | Module 6 | Identifies worst-hit position |
| `test_toolkit_get_tools` | Module 7 | All expected tools are returned |
| `test_toolkit_tool_descriptions` | Module 7 | All tools have docstrings |

### Integration Tests

| Test | Description |
|---|---|
| `test_risk_analyst_workflow` | Risk analyst agent uses toolkit to produce risk summary |
| `test_equity_analyst_piotroski` | Equity analyst scores stocks using F-Score |
| `test_correlation_regime_alert` | Toolkit detects and alerts on correlation regime change |
| `test_stress_test_full_portfolio` | Stress test a multi-asset portfolio through full pipeline |
| `test_yfinance_to_quant` | Data from YFinanceTool flows into QuantToolkit correctly |

### Test Data / Fixtures

```python
import pytest
import numpy as np
from parrot.tools.quant.models import (
    PortfolioRiskInput, AssetRiskInput, PiotroskiInput, StressScenario
)

@pytest.fixture
def sample_returns():
    """60 days of simulated returns."""
    np.random.seed(42)
    return list(np.random.normal(0.001, 0.02, 60))

@pytest.fixture
def sample_benchmark_returns():
    """60 days of SPY-like returns."""
    np.random.seed(123)
    return list(np.random.normal(0.0008, 0.015, 60))

@pytest.fixture
def sample_portfolio_input(sample_returns, sample_benchmark_returns):
    return PortfolioRiskInput(
        returns_data={
            "AAPL": sample_returns,
            "SPY": sample_benchmark_returns,
        },
        weights=[0.6, 0.4],
        symbols=["AAPL", "SPY"],
        confidence=0.95,
        risk_free_rate=0.04,
        annualization_factor=252,
    )

@pytest.fixture
def sample_piotroski_input():
    return PiotroskiInput(
        quarterly_financials={
            "net_income": 15_000_000,
            "total_assets": 100_000_000,
            "operating_cash_flow": 18_000_000,
            "current_assets": 40_000_000,
            "current_liabilities": 20_000_000,
            "long_term_debt": 25_000_000,
            "shares_outstanding": 10_000_000,
            "revenue": 80_000_000,
            "gross_profit": 32_000_000,
        },
        prior_year_financials={
            "total_assets": 95_000_000,
            "current_ratio": 1.8,
            "long_term_debt": 28_000_000,
            "shares_outstanding": 10_000_000,
            "asset_turnover": 0.75,
            "gross_margin": 0.38,
        },
    )

@pytest.fixture
def covid_crash_scenario():
    return StressScenario(
        name="covid_crash_2020",
        asset_shocks={"SPY": -0.34, "BTC": -0.50, "AAPL": -0.30, "TLT": 0.20},
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All Pydantic data models defined and validated
- [ ] Risk metrics engine implements VaR, CVaR, beta, Sharpe, drawdown (single + portfolio)
- [ ] Portfolio VaR supports parametric and historical methods
- [ ] Correlation engine computes Pearson/Spearman/Kendall on **returns** (not prices)
- [ ] Correlation regime detection flags pairs with >2 std deviation
- [ ] Cross-asset correlation handles calendar alignment
- [ ] Piotroski F-Score implements all 9 criteria with data completeness tracking
- [ ] Volatility module implements close-to-close, Parkinson, Garman-Klass estimators
- [ ] Volatility cone produces percentile ranks across multiple windows
- [ ] Stress testing applies scenarios and identifies worst positions
- [ ] `QuantToolkit` exposes all tools via `get_tools()` compatible with `Agent`
- [ ] All unit tests pass: `pytest tests/tools/test_quant/ -v`
- [ ] Integration tests pass with finance crew agents
- [ ] Output structures match fields needed by `AnalystReport` schema
- [ ] No blocking I/O — fully async
- [ ] All tools have descriptive docstrings (used as LLM tool descriptions)
- [ ] No new external dependencies (numpy, pandas, scipy already in project)

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- Use `AbstractToolkit` pattern from `parrot/tools/toolkit.py`
- See `parrot/tools/ibkr/` for multi-file toolkit package structure
- Pydantic models for all structured data
- Async-first: all toolkit methods are `async def`
- Comprehensive logging with `self.logger`
- Pure functions where possible (stateless computation)

### Reference Implementations
- `trading_skills/src/trading_skills/risk.py` (95 lines) — single-asset VaR, beta, Sharpe, drawdown
- `trading_skills/src/trading_skills/correlation.py` (39 lines) — basic Pearson correlation
- `trading_skills/src/trading_skills/piotroski.py` (306 lines) — complete 9-criterion F-Score

### Known Risks / Gotchas
- **Correlation on prices vs returns**: trading_skills correlates prices directly (`price_df.corr()`) — this is wrong. Always correlate on returns to avoid spurious correlation from random walks.
- **Annualization factor**: Mixed portfolios (equity + crypto) need weighted-average approach or separate calculation. Default to asset-class-specific factors.
- **VaR assumptions**: Parametric VaR assumes normal distribution (often violated in finance). Historical VaR is more robust but needs sufficient data.
- **Piotroski data availability**: Not all 9 criteria may have data. Must track `data_completeness_pct` and adjust interpretation.
- **Calendar alignment**: Crypto trades 24/7 (365 days), equities M-F (252 days). Cross-asset correlation must align on common timestamps.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `numpy` | existing | Numerical computation, covariance matrices |
| `pandas` | existing | DataFrame operations, rolling windows |
| `scipy.stats` | existing | Statistical distributions for VaR, percentile calculations |

---

## 7. Open Questions

> Questions that must be resolved before or during implementation.

- [ ] **Monte Carlo VaR** — Worth implementing in Phase 1, or defer? Useful for portfolios with options but computationally expensive. — *Owner: defer to Phase 2 unless options integration is immediate*
- [ ] **Risk budget framework** — The risk analyst output includes `risk_budget_used_pct`. Should QuantToolkit define what "risk budget" means, or should that be configuration in `ExecutorConstraints`? — *Owner: define in ExecutorConstraints, QuantToolkit only computes raw metrics*
- [ ] **Annualization for mixed portfolios** — For 60% equity + 40% crypto, use 252, 365, or weighted average? — *Owner: implement asset-class-weighted approach, allow override*
- [ ] **Redis caching** — Should heavier computations (portfolio VaR, correlation regimes) be cached with TTL? — *Owner: defer to caller; toolkit remains stateless*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-02 | Jesus Lara | Initial draft from brainstorming doc |
