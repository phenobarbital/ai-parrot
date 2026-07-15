---
type: Wiki Summary
title: parrot_tools.quant.correlation
id: mod:parrot_tools.quant.correlation
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Correlation Engine for QuantToolkit.
relates_to:
- concept: func:parrot_tools.quant.correlation.compute_correlation_from_input
  rel: defines
- concept: func:parrot_tools.quant.correlation.compute_correlation_matrix
  rel: defines
- concept: func:parrot_tools.quant.correlation.compute_cross_asset_correlation
  rel: defines
- concept: func:parrot_tools.quant.correlation.compute_pairwise_correlation
  rel: defines
- concept: func:parrot_tools.quant.correlation.compute_rolling_correlation
  rel: defines
- concept: func:parrot_tools.quant.correlation.detect_correlation_regimes
  rel: defines
- concept: func:parrot_tools.quant.correlation.get_correlation_heatmap_data
  rel: defines
- concept: func:parrot_tools.quant.correlation.prices_to_returns
  rel: defines
- concept: mod:parrot_tools.quant.models
  rel: references
---

# `parrot_tools.quant.correlation`

Correlation Engine for QuantToolkit.

Provides correlation analysis for portfolio risk monitoring:
- Correlation matrix computation (Pearson, Spearman, Kendall)
- Correlation regime detection (short vs long-term shifts)
- Cross-asset correlation with calendar alignment

CRITICAL: Always correlate on returns, NOT prices.
Correlating prices gives spurious correlations due to random walk behavior.

## Functions

- `def prices_to_returns(prices: np.ndarray) -> np.ndarray` — Convert price series to returns.
- `def compute_correlation_matrix(price_data: dict[str, list[float]], method: Literal['pearson', 'spearman', 'kendall']='pearson', returns_based: bool=True) -> dict` — Compute correlation matrix for multiple assets.
- `def compute_correlation_from_input(inp: CorrelationInput) -> dict` — Compute correlation matrix from CorrelationInput model.
- `def detect_correlation_regimes(price_data: dict[str, list[float]], short_window: int=20, long_window: int=120, z_threshold: float=2.0) -> dict` — Compare short-term vs long-term correlations to detect regime changes.
- `def compute_cross_asset_correlation(equity_prices: dict[str, list[float]], crypto_prices: dict[str, list[float]], timestamps_equity: list[str], timestamps_crypto: list[str], alignment: str='daily_close') -> dict` — Compute correlation between equities (252 trading days) and crypto (365 days).
- `def compute_pairwise_correlation(returns_a: list[float], returns_b: list[float], method: Literal['pearson', 'spearman', 'kendall']='pearson') -> float` — Compute correlation between two return series.
- `def compute_rolling_correlation(returns_a: list[float], returns_b: list[float], window: int=20) -> np.ndarray` — Compute rolling correlation between two return series.
- `def get_correlation_heatmap_data(price_data: dict[str, list[float]], method: Literal['pearson', 'spearman', 'kendall']='pearson') -> dict` — Get correlation data formatted for heatmap visualization.
