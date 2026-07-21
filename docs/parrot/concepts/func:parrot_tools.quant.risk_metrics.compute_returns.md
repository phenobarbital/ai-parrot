---
type: Concept
title: compute_returns()
id: func:parrot_tools.quant.risk_metrics.compute_returns
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Convert price series to daily returns.
---

# compute_returns

```python
def compute_returns(prices: list[float]) -> np.ndarray
```

Convert price series to daily returns.

Args:
    prices: List of closing prices.

Returns:
    Array of daily returns (pct_change).
