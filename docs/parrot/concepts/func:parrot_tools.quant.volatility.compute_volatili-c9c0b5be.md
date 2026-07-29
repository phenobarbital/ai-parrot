---
type: Concept
title: compute_volatility_term_structure()
id: func:parrot_tools.quant.volatility.compute_volatility_term_structure
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Compute volatility across different time horizons.
---

# compute_volatility_term_structure

```python
def compute_volatility_term_structure(returns: list[float], windows: list[int] | None=None, annualization: int=252) -> dict
```

Compute volatility across different time horizons.

Args:
    returns: Daily return series.
    windows: List of window sizes. Default: [5, 10, 20, 60, 120].
    annualization: Annualization factor.

Returns:
    Dictionary with {window: volatility}.
