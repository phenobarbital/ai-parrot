---
type: Concept
title: compute_volatility_single()
id: func:parrot_tools.quant.volatility.compute_volatility_single
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Compute single volatility value from returns.
---

# compute_volatility_single

```python
def compute_volatility_single(returns: list[float], annualization: int=252) -> float
```

Compute single volatility value from returns.

Args:
    returns: Return series.
    annualization: Annualization factor.

Returns:
    Annualized volatility.
