---
type: Concept
title: compute_max_drawdown()
id: func:parrot_tools.quant.risk_metrics.compute_max_drawdown
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Maximum drawdown from cumulative returns.
---

# compute_max_drawdown

```python
def compute_max_drawdown(returns: np.ndarray) -> float
```

Maximum drawdown from cumulative returns.

Args:
    returns: Array of daily returns.

Returns:
    Maximum drawdown as a decimal (negative value).
