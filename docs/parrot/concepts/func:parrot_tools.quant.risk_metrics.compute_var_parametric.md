---
type: Concept
title: compute_var_parametric()
id: func:parrot_tools.quant.risk_metrics.compute_var_parametric
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parametric VaR assuming normal distribution.
---

# compute_var_parametric

```python
def compute_var_parametric(returns: np.ndarray, confidence: float=0.95) -> float
```

Parametric VaR assuming normal distribution.

VaR_alpha = mu + z_alpha * sigma

Where z_alpha is the z-score for the (1-confidence) quantile.

Args:
    returns: Array of daily returns.
    confidence: Confidence level (e.g., 0.95 for 95%).

Returns:
    VaR as a decimal (negative value indicates loss).
