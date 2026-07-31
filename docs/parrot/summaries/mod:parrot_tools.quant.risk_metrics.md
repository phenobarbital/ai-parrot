---
type: Wiki Summary
title: parrot_tools.quant.risk_metrics
id: mod:parrot_tools.quant.risk_metrics
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Risk Metrics Engine for QuantToolkit.
relates_to:
- concept: func:parrot_tools.quant.risk_metrics.compute_beta
  rel: defines
- concept: func:parrot_tools.quant.risk_metrics.compute_cvar
  rel: defines
- concept: func:parrot_tools.quant.risk_metrics.compute_exposure
  rel: defines
- concept: func:parrot_tools.quant.risk_metrics.compute_max_drawdown
  rel: defines
- concept: func:parrot_tools.quant.risk_metrics.compute_portfolio_cvar
  rel: defines
- concept: func:parrot_tools.quant.risk_metrics.compute_portfolio_risk
  rel: defines
- concept: func:parrot_tools.quant.risk_metrics.compute_portfolio_var_historical
  rel: defines
- concept: func:parrot_tools.quant.risk_metrics.compute_portfolio_var_parametric
  rel: defines
- concept: func:parrot_tools.quant.risk_metrics.compute_returns
  rel: defines
- concept: func:parrot_tools.quant.risk_metrics.compute_rolling_metrics
  rel: defines
- concept: func:parrot_tools.quant.risk_metrics.compute_sharpe_ratio
  rel: defines
- concept: func:parrot_tools.quant.risk_metrics.compute_single_asset_risk
  rel: defines
- concept: func:parrot_tools.quant.risk_metrics.compute_var_historical
  rel: defines
- concept: func:parrot_tools.quant.risk_metrics.compute_var_parametric
  rel: defines
- concept: func:parrot_tools.quant.risk_metrics.compute_volatility_annual
  rel: defines
- concept: mod:parrot_tools.quant.models
  rel: references
---

# `parrot_tools.quant.risk_metrics`

Risk Metrics Engine for QuantToolkit.

Provides comprehensive risk calculations for single assets and portfolios:
- VaR (Value at Risk) - parametric and historical methods
- CVaR (Conditional VaR / Expected Shortfall)
- Beta vs benchmark
- Sharpe ratio
- Maximum drawdown
- Rolling metrics

## Functions

- `def compute_returns(prices: list[float]) -> np.ndarray` — Convert price series to daily returns.
- `def compute_var_parametric(returns: np.ndarray, confidence: float=0.95) -> float` — Parametric VaR assuming normal distribution.
- `def compute_var_historical(returns: np.ndarray, confidence: float=0.95) -> float` — Historical VaR using empirical percentile.
- `def compute_cvar(returns: np.ndarray, confidence: float=0.95) -> float` — Conditional VaR (Expected Shortfall).
- `def compute_max_drawdown(returns: np.ndarray) -> float` — Maximum drawdown from cumulative returns.
- `def compute_beta(asset_returns: np.ndarray, benchmark_returns: np.ndarray) -> float` — Beta = Cov(asset, benchmark) / Var(benchmark).
- `def compute_sharpe_ratio(returns: np.ndarray, risk_free_rate: float=0.04, annualization_factor: int=252) -> float` — Annualized Sharpe ratio.
- `def compute_volatility_annual(returns: np.ndarray, annualization_factor: int=252) -> float` — Annualized volatility.
- `def compute_portfolio_var_parametric(returns_df: pd.DataFrame, weights: np.ndarray, confidence: float=0.95) -> float` — Portfolio VaR using variance-covariance method.
- `def compute_portfolio_var_historical(returns_df: pd.DataFrame, weights: np.ndarray, confidence: float=0.95) -> float` — Portfolio VaR using historical simulation.
- `def compute_portfolio_cvar(returns_df: pd.DataFrame, weights: np.ndarray, confidence: float=0.95) -> float` — Portfolio CVaR (Expected Shortfall).
- `def compute_rolling_metrics(returns: np.ndarray, window: int=20, risk_free_rate: float=0.04, annualization_factor: int=252, benchmark_returns: np.ndarray | None=None) -> dict[str, np.ndarray]` — Compute rolling risk metrics.
- `def compute_single_asset_risk(inp: AssetRiskInput) -> RiskMetricsOutput` — Compute all risk metrics for a single asset.
- `def compute_portfolio_risk(inp: PortfolioRiskInput) -> PortfolioRiskOutput` — Compute all risk metrics for a portfolio.
- `def compute_exposure(weights: list[float]) -> dict[str, float]` — Compute net and gross exposure from weights.
