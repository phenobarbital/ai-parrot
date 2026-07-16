---
type: Concept
title: compute_sharpe_ratio()
id: func:parrot_tools.quant.risk_metrics.compute_sharpe_ratio
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Annualized Sharpe ratio.
---

# compute_sharpe_ratio

```python
def compute_sharpe_ratio(returns: np.ndarray, risk_free_rate: float=0.04, annualization_factor: int=252) -> float
```

Annualized Sharpe ratio.

Sharpe = (annualized_return - risk_free_rate) / annualized_volatility

Args:
    returns: Array of daily returns.
    risk_free_rate: Annualized risk-free rate (e.g., 0.04 for 4%).
    annualization_factor: Trading days per year (252 for stocks, 365 for crypto).

Returns:
    Annualized Sharpe ratio.
