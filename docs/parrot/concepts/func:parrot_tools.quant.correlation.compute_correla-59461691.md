---
type: Concept
title: compute_correlation_matrix()
id: func:parrot_tools.quant.correlation.compute_correlation_matrix
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Compute correlation matrix for multiple assets.
---

# compute_correlation_matrix

```python
def compute_correlation_matrix(price_data: dict[str, list[float]], method: Literal['pearson', 'spearman', 'kendall']='pearson', returns_based: bool=True) -> dict
```

Compute correlation matrix for multiple assets.

IMPORTANT: Always correlate returns, not prices.
Correlating prices gives spurious correlations due to random walk behavior.

Args:
    price_data: Dictionary of {symbol: [prices]}.
    method: Correlation method ('pearson', 'spearman', 'kendall').
    returns_based: If True, convert prices to returns first (recommended).

Returns:
    Dictionary with:
    - matrix: Nested dict {symbol: {symbol: correlation}}
    - method: The method used
    - returns_based: Whether returns were used
