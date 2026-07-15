---
type: Concept
title: compute_var_historical()
id: func:parrot_tools.quant.risk_metrics.compute_var_historical
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Historical VaR using empirical percentile.
---

# compute_var_historical

```python
def compute_var_historical(returns: np.ndarray, confidence: float=0.95) -> float
```

Historical VaR using empirical percentile.

Args:
    returns: Array of daily returns.
    confidence: Confidence level (e.g., 0.95 for 95%).

Returns:
    VaR as a decimal (negative value indicates loss).
