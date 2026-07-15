---
type: Concept
title: compute_rolling_metrics()
id: func:parrot_tools.quant.risk_metrics.compute_rolling_metrics
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Compute rolling risk metrics.
---

# compute_rolling_metrics

```python
def compute_rolling_metrics(returns: np.ndarray, window: int=20, risk_free_rate: float=0.04, annualization_factor: int=252, benchmark_returns: np.ndarray | None=None) -> dict[str, np.ndarray]
```

Compute rolling risk metrics.

Args:
    returns: Array of daily returns.
    window: Rolling window size.
    risk_free_rate: Annualized risk-free rate.
    annualization_factor: Trading days per year.
    benchmark_returns: Optional benchmark for beta calculation.

Returns:
    Dictionary with rolling metrics arrays:
    - rolling_vol: Rolling annualized volatility
    - rolling_sharpe: Rolling Sharpe ratio
    - rolling_var_95: Rolling 95% VaR
    - rolling_beta: Rolling beta (if benchmark provided)
