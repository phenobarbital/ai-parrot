---
type: Concept
title: compute_volatility_annual()
id: func:parrot_tools.quant.risk_metrics.compute_volatility_annual
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Annualized volatility.
---

# compute_volatility_annual

```python
def compute_volatility_annual(returns: np.ndarray, annualization_factor: int=252) -> float
```

Annualized volatility.

Args:
    returns: Array of daily returns.
    annualization_factor: Trading days per year.

Returns:
    Annualized volatility.
