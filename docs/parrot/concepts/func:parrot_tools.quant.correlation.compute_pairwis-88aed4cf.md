---
type: Concept
title: compute_pairwise_correlation()
id: func:parrot_tools.quant.correlation.compute_pairwise_correlation
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Compute correlation between two return series.
---

# compute_pairwise_correlation

```python
def compute_pairwise_correlation(returns_a: list[float], returns_b: list[float], method: Literal['pearson', 'spearman', 'kendall']='pearson') -> float
```

Compute correlation between two return series.

Args:
    returns_a: First return series.
    returns_b: Second return series.
    method: Correlation method.

Returns:
    Correlation coefficient.

Raises:
    ValueError: If series have different lengths.
