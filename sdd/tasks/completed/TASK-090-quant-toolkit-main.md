# TASK-090: QuantToolkit Main Class

**Feature**: FEAT-017 QuantToolkit
**Spec**: `sdd/specs/quant-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-084, TASK-085, TASK-086, TASK-087, TASK-088, TASK-089
**Assigned-to**: claude-opus-session

---

## Context

This task implements the main `QuantToolkit` class that inherits from `AbstractToolkit` and exposes all quantitative functions as agent tools. This is the integration point that agents use to access risk metrics, correlation analysis, Piotroski scoring, volatility analytics, and stress testing.

Reference: Spec Section 3 (Module 7: QuantToolkit).

---

## Scope

- Create the `QuantToolkit` class inheriting from `AbstractToolkit`
- Expose all module functions as async toolkit methods:
  - Risk metrics: `compute_risk_metrics`, `compute_portfolio_risk`, `compute_rolling_metrics`
  - Correlation: `compute_correlation_matrix`, `detect_correlation_regimes`, `compute_cross_asset_correlation`
  - Piotroski: `calculate_piotroski_score`, `batch_piotroski_scores`
  - Volatility: `compute_realized_volatility`, `compute_volatility_cone`, `compute_iv_rv_spread`
  - Stress testing: `stress_test_portfolio`
- Ensure all methods have descriptive docstrings (used as LLM tool descriptions)
- Export from package `__init__.py`
- Write integration tests for the toolkit

**NOT in scope**:
- Implementation of computation logic (done in TASK-077 through TASK-078)
- End-to-end agent integration tests (TASK-080)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/quant/toolkit.py` | CREATE | Main QuantToolkit class |
| `parrot/tools/quant/__init__.py` | MODIFY | Export QuantToolkit and models |
| `tests/tools/test_quant/test_toolkit.py` | CREATE | Toolkit integration tests |

---

## Implementation Notes

### Pattern to Follow

```python
# parrot/tools/quant/toolkit.py
from typing import Literal
from ..toolkit import AbstractToolkit
from .models import (
    PortfolioRiskInput, AssetRiskInput, CorrelationInput,
    StressScenario, PiotroskiInput, RiskMetricsOutput, PortfolioRiskOutput,
)
from . import risk_metrics
from . import correlation
from . import piotroski
from . import volatility
from . import stress_testing


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

    Example usage:
        toolkit = QuantToolkit()
        tools = await toolkit.get_tools()
        # Agent can now use: compute_risk_metrics, compute_portfolio_risk, etc.
    """

    name = "quant_toolkit"

    # ===== RISK METRICS =====

    async def compute_risk_metrics(
        self,
        returns: list[float],
        benchmark_returns: list[float] | None = None,
        risk_free_rate: float = 0.04,
        annualization_factor: int = 252,
    ) -> dict:
        """
        Compute risk metrics for a single asset.

        Calculates VaR, CVaR, beta, Sharpe ratio, and maximum drawdown.

        Args:
            returns: Daily return series
            benchmark_returns: Benchmark returns for beta calculation (optional)
            risk_free_rate: Annualized risk-free rate (default 4%)
            annualization_factor: Trading days per year (252 stocks, 365 crypto)

        Returns:
            {
                "volatility_annual": float,
                "beta": float | None,
                "sharpe_ratio": float,
                "max_drawdown": float,
                "var_95": float,
                "var_99": float,
                "cvar_95": float,
            }
        """
        return risk_metrics.compute_single_asset_risk(
            returns=returns,
            benchmark_returns=benchmark_returns,
            risk_free_rate=risk_free_rate,
            annualization_factor=annualization_factor,
        )

    async def compute_portfolio_risk(
        self,
        returns_data: dict[str, list[float]],
        weights: list[float],
        symbols: list[str],
        confidence: float = 0.95,
        risk_free_rate: float = 0.04,
        annualization_factor: int = 252,
        method: Literal["parametric", "historical"] = "parametric",
    ) -> dict:
        """
        Compute portfolio-level risk metrics.

        Calculates portfolio VaR, CVaR, beta, Sharpe, and exposures.

        Args:
            returns_data: Dict of {symbol: [daily_returns]}
            weights: Position weights (must sum to 1.0)
            symbols: Symbol names matching returns_data keys
            confidence: VaR confidence level (default 0.95)
            risk_free_rate: Annualized risk-free rate
            annualization_factor: Trading days per year
            method: VaR method - "parametric" or "historical"

        Returns:
            {
                "var_1d_95_usd": float,
                "var_1d_99_usd": float,
                "cvar_1d_95_usd": float,
                "portfolio_volatility": float,
                "portfolio_beta": float | None,
                "portfolio_sharpe": float,
                "max_drawdown": float,
                "net_exposure": float,
                "gross_exposure": float,
            }
        """
        return risk_metrics.compute_portfolio_risk(
            returns_data=returns_data,
            weights=weights,
            symbols=symbols,
            confidence=confidence,
            risk_free_rate=risk_free_rate,
            annualization_factor=annualization_factor,
            method=method,
        )

    async def compute_rolling_metrics(
        self,
        returns: list[float],
        window: int = 60,
        benchmark_returns: list[float] | None = None,
    ) -> dict:
        """
        Compute rolling risk metrics for regime detection.

        Args:
            returns: Daily return series
            window: Rolling window size in trading days
            benchmark_returns: Benchmark for beta calculation

        Returns:
            {
                "rolling_vol": list[float],
                "rolling_sharpe": list[float],
                "rolling_var95": list[float],
                "rolling_beta": list[float] | None,
            }
        """
        return risk_metrics.compute_rolling_metrics(
            returns=returns,
            window=window,
            benchmark_returns=benchmark_returns,
        )

    # ===== CORRELATION =====

    async def compute_correlation_matrix(
        self,
        price_data: dict[str, list[float]],
        method: Literal["pearson", "spearman", "kendall"] = "pearson",
        returns_based: bool = True,
    ) -> dict:
        """
        Compute correlation matrix for multiple assets.

        IMPORTANT: Correlates returns by default (not prices) to avoid
        spurious correlation from random walk behavior.

        Args:
            price_data: Dict of {symbol: [close_prices]}
            method: Correlation method
            returns_based: If True, convert prices to returns first (recommended)

        Returns:
            {
                "matrix": {symbol: {symbol: correlation}},
                "method": str,
                "returns_based": bool,
            }
        """
        return correlation.compute_correlation_matrix(
            price_data=price_data,
            method=method,
            returns_based=returns_based,
        )

    async def detect_correlation_regimes(
        self,
        price_data: dict[str, list[float]],
        short_window: int = 20,
        long_window: int = 120,
        z_threshold: float = 2.0,
    ) -> dict:
        """
        Detect correlation regime changes.

        Compares short-term vs long-term correlations and flags pairs
        where the deviation exceeds the z-threshold.

        Args:
            price_data: Dict of {symbol: [close_prices]}
            short_window: Recent window for comparison
            long_window: Historical window for baseline
            z_threshold: Standard deviations for alert (default 2.0)

        Returns:
            {
                "regime_alerts": [
                    {"pair": "NVDA-SPY", "short_corr": 0.85, "long_corr": 0.45,
                     "z_score": 2.8, "alert": "correlation_spike"}
                ],
                "correlation_matrix_short": {...},
                "correlation_matrix_long": {...},
            }
        """
        return correlation.detect_correlation_regimes(
            price_data=price_data,
            short_window=short_window,
            long_window=long_window,
            z_threshold=z_threshold,
        )

    async def compute_cross_asset_correlation(
        self,
        equity_prices: dict[str, list[float]],
        crypto_prices: dict[str, list[float]],
        timestamps_equity: list[str],
        timestamps_crypto: list[str],
    ) -> dict:
        """
        Compute correlation between equities and crypto with calendar alignment.

        Handles different trading calendars (equity: 252 days, crypto: 365 days).

        Args:
            equity_prices: {symbol: [prices]} for equities
            crypto_prices: {symbol: [prices]} for crypto
            timestamps_equity: Date strings for equity prices
            timestamps_crypto: Date strings for crypto prices

        Returns:
            {
                "cross_asset_correlations": {"SPY-BTC": 0.45, ...},
                "full_matrix": {...},
                "common_dates_count": int,
            }
        """
        return correlation.compute_cross_asset_correlation(
            equity_prices=equity_prices,
            crypto_prices=crypto_prices,
            timestamps_equity=timestamps_equity,
            timestamps_crypto=timestamps_crypto,
        )

    # ===== PIOTROSKI F-SCORE =====

    async def calculate_piotroski_score(
        self,
        quarterly_financials: dict[str, float],
        prior_year_financials: dict[str, float],
    ) -> dict:
        """
        Calculate Piotroski F-Score (0-9) for fundamental quality.

        Evaluates company financial health using 9 accounting criteria:
        - Profitability: positive NI, ROA, OCF, OCF>NI (4 points)
        - Leverage: lower debt, higher current ratio, no dilution (3 points)
        - Efficiency: higher gross margin, higher asset turnover (2 points)

        Args:
            quarterly_financials: Current quarter financial data
            prior_year_financials: Prior year data for YoY comparison

        Returns:
            {
                "total_score": int (0-9),
                "criteria": {...},
                "data_completeness_pct": float,
                "interpretation": "Excellent" | "Good" | "Fair" | "Poor",
                "category_scores": {...},
            }
        """
        from .models import PiotroskiInput
        input_data = PiotroskiInput(
            quarterly_financials=quarterly_financials,
            prior_year_financials=prior_year_financials,
        )
        return piotroski.calculate_piotroski_score(input_data)

    async def batch_piotroski_scores(
        self,
        symbols_data: dict[str, dict],
    ) -> dict:
        """
        Calculate F-Scores for multiple stocks.

        Args:
            symbols_data: {symbol: {"quarterly_financials": {...}, "prior_year_financials": {...}}}

        Returns:
            {symbol: {score_result}}
        """
        from .models import PiotroskiInput
        inputs = {
            symbol: PiotroskiInput(**data)
            for symbol, data in symbols_data.items()
        }
        return piotroski.batch_piotroski_scores(inputs)

    # ===== VOLATILITY =====

    async def compute_realized_volatility(
        self,
        returns: list[float],
        window: int = 20,
        annualization: int = 252,
        method: Literal["close_to_close", "parkinson", "garman_klass"] = "close_to_close",
        ohlc_data: dict[str, list[float]] | None = None,
    ) -> list[float]:
        """
        Compute rolling realized volatility.

        Methods:
        - close_to_close: Standard deviation of returns (most common)
        - parkinson: Uses high-low range (~5x more efficient)
        - garman_klass: Uses OHLC (most efficient)

        Args:
            returns: Daily return series
            window: Rolling window size
            annualization: 252 for stocks, 365 for crypto
            method: Volatility estimator
            ohlc_data: Required for parkinson/garman_klass

        Returns:
            List of rolling annualized volatility values
        """
        return volatility.compute_realized_volatility(
            returns=returns,
            window=window,
            annualization=annualization,
            method=method,
            ohlc_data=ohlc_data,
        )

    async def compute_volatility_cone(
        self,
        returns: list[float],
        windows: list[int] = [10, 20, 30, 60, 90, 120],
    ) -> dict:
        """
        Compute percentile ranks of current volatility across multiple windows.

        Answers: "Is current 20-day vol high or low relative to history?"

        Args:
            returns: Daily return series
            windows: List of lookback windows to analyze

        Returns:
            {
                window: {
                    "current": float,
                    "percentile": float (0-100),
                    "min": float,
                    "max": float,
                    "median": float,
                }
            }
        """
        return volatility.compute_volatility_cone(
            returns=returns,
            windows=windows,
        )

    async def compute_iv_rv_spread(
        self,
        implied_vol: float,
        realized_vol_series: list[float],
        window: int = 20,
    ) -> dict:
        """
        Compute IV vs RV spread for options sentiment analysis.

        - IV >> RV: Fear premium is elevated (contrarian buy signal)
        - IV << RV: Complacency (contrarian sell signal)

        Args:
            implied_vol: Current implied volatility (annualized)
            realized_vol_series: Historical realized vol series
            window: Window for current RV calculation

        Returns:
            {
                "implied_vol": float,
                "realized_vol": float,
                "spread": float,
                "spread_pct": float,
                "regime": "fear_premium" | "complacent" | "normal",
            }
        """
        return volatility.compute_iv_rv_spread(
            implied_vol=implied_vol,
            realized_vol_series=realized_vol_series,
            window=window,
        )

    # ===== STRESS TESTING =====

    async def stress_test_portfolio(
        self,
        portfolio_values: dict[str, float],
        scenario_names: list[str] | None = None,
        custom_scenarios: list[dict] | None = None,
    ) -> dict:
        """
        Apply stress scenarios to a portfolio and estimate losses.

        Predefined scenarios: covid_crash_2020, rate_hike_shock, crypto_winter, black_swan

        Args:
            portfolio_values: {symbol: current_market_value}
            scenario_names: List of predefined scenario names to apply
            custom_scenarios: Custom scenarios as [{"name": str, "asset_shocks": {...}}]

        Returns:
            {
                "scenario_results": {
                    "scenario_name": {
                        "portfolio_loss_pct": float,
                        "portfolio_loss_usd": float,
                        "position_impacts": {...},
                        "worst_position": str,
                    }
                },
                "worst_scenario": str,
                "max_loss_pct": float,
            }
        """
        scenarios = []

        # Add predefined scenarios
        if scenario_names:
            for name in scenario_names:
                scenarios.append(stress_testing.get_predefined_scenario(name))

        # Add custom scenarios
        if custom_scenarios:
            from .models import StressScenario
            for s in custom_scenarios:
                scenarios.append(StressScenario(**s))

        if not scenarios:
            # Default to all predefined scenarios
            scenario_names = stress_testing.list_predefined_scenarios()
            scenarios = [stress_testing.get_predefined_scenario(n) for n in scenario_names]

        symbols = list(portfolio_values.keys())
        weights = [v / sum(portfolio_values.values()) for v in portfolio_values.values()]

        return stress_testing.stress_test_portfolio(
            portfolio_values=portfolio_values,
            weights=weights,
            symbols=symbols,
            scenarios=scenarios,
        )
```

### Package __init__.py

```python
# parrot/tools/quant/__init__.py
"""
QuantToolkit - Quantitative risk analysis and portfolio metrics.

Provides computational tools for:
- Risk metrics (VaR, CVaR, beta, Sharpe, drawdown)
- Correlation analysis and regime detection
- Piotroski F-Score fundamental scoring
- Volatility analytics
- Stress testing
"""

from .toolkit import QuantToolkit
from .models import (
    PortfolioRiskInput,
    AssetRiskInput,
    CorrelationInput,
    StressScenario,
    PiotroskiInput,
    RiskMetricsOutput,
    PortfolioRiskOutput,
)

__all__ = [
    "QuantToolkit",
    "PortfolioRiskInput",
    "AssetRiskInput",
    "CorrelationInput",
    "StressScenario",
    "PiotroskiInput",
    "RiskMetricsOutput",
    "PortfolioRiskOutput",
]
```

### Key Constraints
- All methods must be `async def`
- All methods must have comprehensive docstrings (used as tool descriptions)
- Must inherit from `AbstractToolkit`
- Must delegate to underlying module functions (no computation logic in toolkit class)
- Export `QuantToolkit` from package `__init__.py`

### References in Codebase
- `parrot/tools/toolkit.py` — `AbstractToolkit` base class
- `parrot/tools/ibkr/__init__.py` — similar toolkit structure
- `parrot/tools/jiratoolkit.py` — toolkit method patterns

---

## Acceptance Criteria

- [x] `QuantToolkit` inherits from `AbstractToolkit`
- [x] All 12 async methods exposed (per spec Section 2)
- [x] All methods have descriptive docstrings
- [x] `get_tools()` returns all toolkit methods as tools
- [x] Package exports `QuantToolkit` and models
- [x] All tests pass: `pytest tests/tools/test_quant/test_toolkit.py -v`
- [x] Import works: `from parrot.tools.quant import QuantToolkit`

---

## Test Specification

```python
# tests/tools/test_quant/test_toolkit.py
import pytest
import numpy as np
from parrot.tools.quant import QuantToolkit


@pytest.fixture
def toolkit():
    return QuantToolkit()


@pytest.fixture
def sample_returns():
    np.random.seed(42)
    return list(np.random.normal(0.001, 0.02, 100))


class TestToolkitStructure:
    def test_inherits_abstracttoolkit(self, toolkit):
        """QuantToolkit inherits from AbstractToolkit."""
        from parrot.tools.toolkit import AbstractToolkit
        assert isinstance(toolkit, AbstractToolkit)

    def test_toolkit_name(self, toolkit):
        """Toolkit has correct name."""
        assert toolkit.name == "quant_toolkit"

    @pytest.mark.asyncio
    async def test_get_tools_returns_all_methods(self, toolkit):
        """get_tools() returns all expected tools."""
        tools = await toolkit.get_tools()
        tool_names = [t.name for t in tools]

        expected = [
            "compute_risk_metrics",
            "compute_portfolio_risk",
            "compute_rolling_metrics",
            "compute_correlation_matrix",
            "detect_correlation_regimes",
            "compute_cross_asset_correlation",
            "calculate_piotroski_score",
            "batch_piotroski_scores",
            "compute_realized_volatility",
            "compute_volatility_cone",
            "compute_iv_rv_spread",
            "stress_test_portfolio",
        ]

        for name in expected:
            assert name in tool_names, f"Missing tool: {name}"

    @pytest.mark.asyncio
    async def test_tools_have_descriptions(self, toolkit):
        """All tools have docstring descriptions."""
        tools = await toolkit.get_tools()
        for tool in tools:
            assert tool.description, f"Tool {tool.name} missing description"
            assert len(tool.description) > 20, f"Tool {tool.name} description too short"


class TestRiskMetrics:
    @pytest.mark.asyncio
    async def test_compute_risk_metrics(self, toolkit, sample_returns):
        """compute_risk_metrics returns expected structure."""
        result = await toolkit.compute_risk_metrics(sample_returns)
        assert "volatility_annual" in result
        assert "sharpe_ratio" in result
        assert "var_95" in result
        assert "max_drawdown" in result

    @pytest.mark.asyncio
    async def test_compute_portfolio_risk(self, toolkit):
        """compute_portfolio_risk works with portfolio data."""
        np.random.seed(42)
        returns_data = {
            "AAPL": list(np.random.normal(0.001, 0.02, 60)),
            "SPY": list(np.random.normal(0.0008, 0.015, 60)),
        }
        result = await toolkit.compute_portfolio_risk(
            returns_data=returns_data,
            weights=[0.6, 0.4],
            symbols=["AAPL", "SPY"],
        )
        assert "portfolio_volatility" in result
        assert "var_1d_95_usd" in result or "var_1d_95_pct" in result


class TestCorrelation:
    @pytest.mark.asyncio
    async def test_compute_correlation_matrix(self, toolkit):
        """compute_correlation_matrix returns matrix."""
        np.random.seed(42)
        price_data = {
            "AAPL": list(100 * np.cumprod(1 + np.random.normal(0.001, 0.02, 60))),
            "MSFT": list(100 * np.cumprod(1 + np.random.normal(0.001, 0.02, 60))),
        }
        result = await toolkit.compute_correlation_matrix(price_data)
        assert "matrix" in result
        assert "AAPL" in result["matrix"]


class TestPiotroski:
    @pytest.mark.asyncio
    async def test_calculate_piotroski_score(self, toolkit):
        """calculate_piotroski_score returns score."""
        result = await toolkit.calculate_piotroski_score(
            quarterly_financials={
                "net_income": 10_000_000,
                "total_assets": 50_000_000,
                "operating_cash_flow": 12_000_000,
            },
            prior_year_financials={},
        )
        assert "total_score" in result
        assert 0 <= result["total_score"] <= 9


class TestVolatility:
    @pytest.mark.asyncio
    async def test_compute_volatility_cone(self, toolkit, sample_returns):
        """compute_volatility_cone returns cone data."""
        result = await toolkit.compute_volatility_cone(sample_returns)
        assert isinstance(result, dict)


class TestStressTesting:
    @pytest.mark.asyncio
    async def test_stress_test_portfolio(self, toolkit):
        """stress_test_portfolio returns scenario results."""
        portfolio = {"SPY": 50000, "BTC": 30000}
        result = await toolkit.stress_test_portfolio(
            portfolio_values=portfolio,
            scenario_names=["covid_crash_2020"],
        )
        assert "scenario_results" in result
        assert "covid_crash_2020" in result["scenario_results"]


class TestImports:
    def test_import_from_package(self):
        """Can import QuantToolkit from package."""
        from parrot.tools.quant import QuantToolkit
        assert QuantToolkit is not None

    def test_import_models(self):
        """Can import models from package."""
        from parrot.tools.quant import (
            PortfolioRiskInput, AssetRiskInput, StressScenario
        )
        assert PortfolioRiskInput is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/quant-toolkit.spec.md` for full context
2. **Check dependencies** — verify TASK-077 through TASK-078 are in `tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-083-quant-toolkit-main.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-opus-session
**Date**: 2026-03-02
**Notes**:
- Created QuantToolkit class inheriting from AbstractToolkit
- Implemented all 12 async toolkit methods:
  - Risk metrics: compute_risk_metrics, compute_portfolio_risk, compute_rolling_metrics
  - Correlation: compute_correlation_matrix, detect_correlation_regimes, compute_cross_asset_correlation
  - Piotroski: calculate_piotroski_score, batch_piotroski_scores
  - Volatility: compute_realized_volatility, compute_volatility_cone, compute_iv_rv_spread
  - Stress testing: stress_test_portfolio
- All methods have comprehensive docstrings for LLM tool descriptions
- Updated __init__.py to export QuantToolkit at package level
- 33 tests passing for toolkit, 275 total tests for quant module

**Deviations from spec**:
- Risk metric functions (compute_single_asset_risk, compute_portfolio_risk) use Pydantic models internally, toolkit wraps them with dict inputs/outputs for cleaner agent interface
- Rolling metrics returns numpy arrays converted to lists for JSON serialization
- Added annualization parameter to compute_volatility_cone for flexibility
