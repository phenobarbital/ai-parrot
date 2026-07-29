---
type: Concept
title: prices_to_returns()
id: func:parrot_tools.quant.correlation.prices_to_returns
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Convert price series to returns.
---

# prices_to_returns

```python
def prices_to_returns(prices: np.ndarray) -> np.ndarray
```

Convert price series to returns.

Args:
    prices: Array of closing prices.

Returns:
    Array of daily returns (pct_change).
