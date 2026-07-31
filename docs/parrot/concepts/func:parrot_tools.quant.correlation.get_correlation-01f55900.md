---
type: Concept
title: get_correlation_heatmap_data()
id: func:parrot_tools.quant.correlation.get_correlation_heatmap_data
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Get correlation data formatted for heatmap visualization.
---

# get_correlation_heatmap_data

```python
def get_correlation_heatmap_data(price_data: dict[str, list[float]], method: Literal['pearson', 'spearman', 'kendall']='pearson') -> dict
```

Get correlation data formatted for heatmap visualization.

Args:
    price_data: Dictionary of {symbol: [prices]}.
    method: Correlation method.

Returns:
    Dictionary with:
    - symbols: List of symbols
    - correlations: 2D list for heatmap
    - method: Method used
