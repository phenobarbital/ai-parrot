# TASK-085: Risk Metrics Engine

**Feature**: FEAT-017 QuantToolkit
**Spec**: `sdd/specs/quant-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-084
**Assigned-to**: claude-opus-session

---

## Context

This task implements the core risk metrics engine — the computational heart of the QuantToolkit. It provides VaR, CVaR, beta, Sharpe ratio, and maximum drawdown calculations for both single assets and portfolios.

This module is critical for the risk analyst crew's quantitative analysis capabilities.

Reference: Spec Section 3 (Module 2: Risk Metrics Engine).

---

## Scope

- Implement single-asset risk metrics:
  - Daily returns calculation
  - Annualized volatility
  - Beta vs benchmark (covariance/variance method)
  - Sharpe ratio
  - Maximum drawdown
  - VaR at 95% and 99% confidence (parametric method)
  - CVaR (Conditional VaR / Expected Shortfall)
- Implement portfolio-level risk metrics:
  - Portfolio VaR using variance-covariance method (parametric)
  - Portfolio VaR using historical method (empirical percentile)
  - Portfolio CVaR
  - Portfolio beta and Sharpe
  - Net and gross exposure
- Implement rolling metrics:
  - Rolling volatility, beta, Sharpe, VaR
- Write comprehensive unit tests

**NOT in scope**:
- Monte Carlo VaR (deferred to Phase 2 per spec)
- Correlation calculations (TASK-079)
- The main QuantToolkit class (TASK-079)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/quant/risk_metrics.py` | CREATE | Risk metrics engine |
| `tests/tools/test_quant/test_risk_metrics.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

```python
import numpy as np
import pandas as pd
from scipy import stats
from .models import AssetRiskInput, PortfolioRiskInput, RiskMetricsOutput, PortfolioRiskOutput


def compute_returns(prices: list[float]) -> np.ndarray:
    """Convert price series to daily returns."""
    prices_arr = np.array(prices)
    return np.diff(prices_arr) / prices_arr[:-1]


def compute_var_parametric(
    returns: np.ndarray,
    confidence: float = 0.95,
) -> float:
    """
    Parametric VaR assuming normal distribution.

    VaR_alpha = mu - z_alpha * sigma
    """
    mean = np.mean(returns)
    std = np.std(returns, ddof=1)
    z_score = stats.norm.ppf(1 - confidence)
    return mean + z_score * std  # negative value = loss


def compute_cvar(
    returns: np.ndarray,
    confidence: float = 0.95,
) -> float:
    """
    Conditional VaR (Expected Shortfall).
    Average of returns beyond VaR threshold.
    CVaR >= VaR always.
    """
    var = compute_var_parametric(returns, confidence)
    tail_losses = returns[returns <= var]
    if len(tail_losses) == 0:
        return var
    return np.mean(tail_losses)


def compute_max_drawdown(returns: np.ndarray) -> float:
    """Maximum drawdown from cumulative returns."""
    cumulative = (1 + returns).cumprod()
    running_max = np.maximum.accumulate(cumulative)
    drawdown = (cumulative - running_max) / running_max
    return float(np.min(drawdown))


def compute_beta(
    asset_returns: np.ndarray,
    benchmark_returns: np.ndarray,
) -> float:
    """Beta = Cov(asset, benchmark) / Var(benchmark)."""
    if len(asset_returns) != len(benchmark_returns):
        raise ValueError("Returns arrays must have same length")
    covariance = np.cov(asset_returns, benchmark_returns)[0, 1]
    benchmark_var = np.var(benchmark_returns, ddof=1)
    if benchmark_var == 0:
        return 0.0
    return covariance / benchmark_var


def compute_sharpe_ratio(
    returns: np.ndarray,
    risk_free_rate: float = 0.04,
    annualization_factor: int = 252,
) -> float:
    """Annualized Sharpe ratio."""
    excess_return = np.mean(returns) * annualization_factor - risk_free_rate
    annual_vol = np.std(returns, ddof=1) * np.sqrt(annualization_factor)
    if annual_vol == 0:
        return 0.0
    return excess_return / annual_vol


def compute_portfolio_var_parametric(
    returns_df: pd.DataFrame,
    weights: np.ndarray,
    confidence: float = 0.95,
) -> float:
    """
    Portfolio VaR using variance-covariance method.

    portfolio_var = z * sqrt(w' * Cov * w)
    """
    cov_matrix = returns_df.cov().values
    portfolio_var = np.dot(weights, np.dot(cov_matrix, weights))
    portfolio_std = np.sqrt(portfolio_var)
    z_score = stats.norm.ppf(1 - confidence)
    return z_score * portfolio_std


def compute_portfolio_var_historical(
    returns_df: pd.DataFrame,
    weights: np.ndarray,
    confidence: float = 0.95,
) -> float:
    """
    Portfolio VaR using historical simulation.
    Empirical percentile of portfolio returns.
    """
    portfolio_returns = returns_df.values @ weights
    return float(np.percentile(portfolio_returns, (1 - confidence) * 100))
```

### Key Constraints
- Use numpy and pandas for all numerical operations (no new dependencies)
- Use scipy.stats for normal distribution functions
- Always use `ddof=1` for sample standard deviation
- Handle edge cases: zero variance, empty arrays, mismatched lengths
- CVaR must always be >= VaR (more conservative)
- All functions should be pure (no side effects, no state)

### References in Codebase
- `trading_skills/src/trading_skills/risk.py` — reference implementation (95 lines)
- `parrot/finance/schemas.py` — `PortfolioSnapshot.max_drawdown_pct` field

---

## Acceptance Criteria

- [x] Single-asset risk metrics: VaR, CVaR, beta, Sharpe, drawdown
- [x] Portfolio VaR with parametric and historical methods
- [x] Rolling metrics with configurable window
- [x] All tests pass: `pytest tests/tools/test_quant/test_risk_metrics.py -v`
- [x] Edge cases handled (zero variance, empty data)
- [x] CVaR >= VaR in all test cases

---

## Test Specification

```python
# tests/tools/test_quant/test_risk_metrics.py
import pytest
import numpy as np
from parrot.tools.quant.risk_metrics import (
    compute_returns, compute_var_parametric, compute_cvar,
    compute_max_drawdown, compute_beta, compute_sharpe_ratio,
    compute_portfolio_var_parametric, compute_portfolio_var_historical,
    compute_single_asset_risk, compute_portfolio_risk, compute_rolling_metrics,
)


@pytest.fixture
def sample_returns():
    """60 days of simulated returns."""
    np.random.seed(42)
    return np.random.normal(0.001, 0.02, 60)


@pytest.fixture
def sample_benchmark_returns():
    """60 days of benchmark returns."""
    np.random.seed(123)
    return np.random.normal(0.0008, 0.015, 60)


class TestVaR:
    def test_var_parametric_95(self, sample_returns):
        """VaR at 95% confidence."""
        var = compute_var_parametric(sample_returns, 0.95)
        assert var < 0  # Should be a loss
        assert -0.10 < var < 0  # Reasonable range

    def test_var_99_more_conservative(self, sample_returns):
        """VaR at 99% should be more negative than 95%."""
        var_95 = compute_var_parametric(sample_returns, 0.95)
        var_99 = compute_var_parametric(sample_returns, 0.99)
        assert var_99 < var_95  # More conservative


class TestCVaR:
    def test_cvar_greater_than_var(self, sample_returns):
        """CVaR (Expected Shortfall) >= VaR always."""
        var = compute_var_parametric(sample_returns, 0.95)
        cvar = compute_cvar(sample_returns, 0.95)
        assert cvar <= var  # Both negative, CVaR more negative


class TestBeta:
    def test_beta_calculation(self, sample_returns, sample_benchmark_returns):
        """Beta calculation matches manual."""
        beta = compute_beta(sample_returns, sample_benchmark_returns)
        # Manual verification
        cov = np.cov(sample_returns, sample_benchmark_returns)[0, 1]
        var_bench = np.var(sample_benchmark_returns, ddof=1)
        expected = cov / var_bench
        assert abs(beta - expected) < 0.001

    def test_beta_zero_variance(self):
        """Beta is 0 when benchmark has zero variance."""
        asset = np.array([0.01, 0.02, -0.01])
        benchmark = np.array([0.0, 0.0, 0.0])
        beta = compute_beta(asset, benchmark)
        assert beta == 0.0


class TestSharpe:
    def test_sharpe_ratio(self, sample_returns):
        """Sharpe ratio calculation."""
        sharpe = compute_sharpe_ratio(sample_returns, risk_free_rate=0.04)
        assert isinstance(sharpe, float)


class TestMaxDrawdown:
    def test_max_drawdown_known_series(self):
        """Max drawdown on a known series."""
        # Price: 100 -> 120 -> 90 -> 100
        # Returns: +20%, -25%, +11.1%
        returns = np.array([0.20, -0.25, 0.111])
        dd = compute_max_drawdown(returns)
        # After +20%: value=1.2, max=1.2, dd=0
        # After -25%: value=0.9, max=1.2, dd=-0.25
        assert abs(dd - (-0.25)) < 0.01


class TestPortfolioVaR:
    def test_portfolio_var_parametric(self):
        """Portfolio VaR with covariance method."""
        import pandas as pd
        np.random.seed(42)
        returns_df = pd.DataFrame({
            'AAPL': np.random.normal(0.001, 0.02, 60),
            'SPY': np.random.normal(0.0008, 0.015, 60),
        })
        weights = np.array([0.6, 0.4])
        var = compute_portfolio_var_parametric(returns_df, weights, 0.95)
        assert var < 0

    def test_portfolio_var_historical(self):
        """Portfolio VaR with historical simulation."""
        import pandas as pd
        np.random.seed(42)
        returns_df = pd.DataFrame({
            'AAPL': np.random.normal(0.001, 0.02, 60),
            'SPY': np.random.normal(0.0008, 0.015, 60),
        })
        weights = np.array([0.6, 0.4])
        var = compute_portfolio_var_historical(returns_df, weights, 0.95)
        assert var < 0


class TestRollingMetrics:
    def test_rolling_window_length(self, sample_returns):
        """Rolling metrics produce correct output length."""
        result = compute_rolling_metrics(sample_returns, window=20)
        # With 60 samples and window=20, should have 41 points
        assert len(result['rolling_vol']) == 41
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/quant-toolkit.spec.md` for full context
2. **Check dependencies** — verify TASK-084 is in `tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-078-risk-metrics-engine.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-opus-session
**Date**: 2026-03-02
**Notes**:
- Created `parrot/tools/quant/risk_metrics.py` with comprehensive risk metrics engine
- Single-asset metrics: `compute_var_parametric`, `compute_var_historical`, `compute_cvar`, `compute_max_drawdown`, `compute_beta`, `compute_sharpe_ratio`, `compute_volatility_annual`
- Portfolio metrics: `compute_portfolio_var_parametric`, `compute_portfolio_var_historical`, `compute_portfolio_cvar`
- Rolling metrics: `compute_rolling_metrics` with configurable window (vol, sharpe, var, beta)
- High-level wrappers: `compute_single_asset_risk`, `compute_portfolio_risk` using Pydantic models
- All 49 risk metrics tests pass
- Edge cases handled: empty arrays, zero variance, length mismatches
- CVaR >= VaR invariant verified in tests
- Updated `__init__.py` to export all risk metrics functions

**Deviations from spec**: None. Implementation follows spec exactly.
