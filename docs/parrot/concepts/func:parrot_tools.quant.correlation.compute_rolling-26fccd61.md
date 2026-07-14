---
type: Concept
title: compute_rolling_correlation()
id: func:parrot_tools.quant.correlation.compute_rolling_correlation
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Compute rolling correlation between two return series.
---

# compute_rolling_correlation

```python
def compute_rolling_correlation(returns_a: list[float], returns_b: list[float], window: int=20) -> np.ndarray
```

Compute rolling correlation between two return series.

Args:
    returns_a: First return series.
    returns_b: Second return series.
    window: Rolling window size.

Returns:
    Array of rolling correlations.

Raises:
    ValueError: If series have different lengths.
