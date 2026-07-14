---
type: Wiki Entity
title: QuantToolkit
id: class:parrot_tools.quant.toolkit.QuantToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Quantitative risk analysis, portfolio metrics, and fundamental scoring toolkit.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# QuantToolkit

Defined in [`parrot_tools.quant.toolkit`](../summaries/mod:parrot_tools.quant.toolkit.md).

```python
class QuantToolkit(AbstractToolkit)
```

Quantitative risk analysis, portfolio metrics, and fundamental scoring toolkit.

Provides computational tools for:
- Risk metrics (VaR, CVaR, beta, Sharpe, drawdown)
- Correlation analysis and regime detection
- Piotroski F-Score fundamental scoring
- Volatility analytics (realized vol, cone, IV/RV spread)
- Stress testing with predefined scenarios

Example:
    >>> toolkit = QuantToolkit()
    >>> tools = await toolkit.get_tools()
    >>> # Returns 12 tools for agent use

## Methods

- `async def compute_risk_metrics(self, returns: list[float], benchmark_returns: list[float] | None=None, risk_free_rate: float=0.04, annualization_factor: int=252) -> dict` — Compute risk metrics for a single asset.
- `async def compute_portfolio_risk(self, returns_data: dict[str, list[float]], weights: list[float], symbols: list[str], confidence: float=0.95, risk_free_rate: float=0.04, annualization_factor: int=252, method: Literal['parametric', 'historical']='parametric') -> dict` — Compute portfolio-level risk metrics.
- `async def compute_rolling_metrics(self, returns: list[float], window: int=60, benchmark_returns: list[float] | None=None, risk_free_rate: float=0.04, annualization_factor: int=252) -> dict` — Compute rolling risk metrics for regime detection.
- `async def compute_correlation_matrix(self, price_data: dict[str, list[float]], method: Literal['pearson', 'spearman', 'kendall']='pearson', returns_based: bool=True) -> dict` — Compute correlation matrix for multiple assets.
- `async def detect_correlation_regimes(self, price_data: dict[str, list[float]], short_window: int=20, long_window: int=120, z_threshold: float=2.0) -> dict` — Detect correlation regime changes between asset pairs.
- `async def compute_cross_asset_correlation(self, equity_prices: dict[str, list[float]], crypto_prices: dict[str, list[float]], timestamps_equity: list[str], timestamps_crypto: list[str]) -> dict` — Compute correlation between equities and crypto with calendar alignment.
- `async def calculate_piotroski_score(self, quarterly_financials: dict[str, float], prior_year_financials: dict[str, float] | None=None) -> dict` — Calculate Piotroski F-Score (0-9) for fundamental quality assessment.
- `async def batch_piotroski_scores(self, symbols_data: dict[str, dict]) -> dict[str, dict]` — Calculate F-Scores for multiple stocks in batch.
- `async def compute_realized_volatility(self, returns: list[float], window: int=20, annualization: int=252, method: Literal['close_to_close', 'parkinson', 'garman_klass']='close_to_close', ohlc_data: dict[str, list[float]] | None=None) -> list[float]` — Compute rolling realized volatility using various estimators.
- `async def compute_volatility_cone(self, returns: list[float], windows: list[int] | None=None, annualization: int=252) -> dict` — Compute percentile ranks of current volatility across multiple windows.
- `async def compute_iv_rv_spread(self, implied_vol: float, realized_vol_series: list[float], window: int=20) -> dict` — Compute IV vs RV spread for options sentiment analysis.
- `async def stress_test_portfolio(self, portfolio_values: dict[str, float], scenario_names: list[str] | None=None, custom_scenarios: list[dict] | None=None) -> dict` — Apply stress scenarios to a portfolio and estimate potential losses.
