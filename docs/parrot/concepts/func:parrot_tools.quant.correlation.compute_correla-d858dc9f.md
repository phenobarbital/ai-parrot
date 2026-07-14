---
type: Concept
title: compute_correlation_from_input()
id: func:parrot_tools.quant.correlation.compute_correlation_from_input
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Compute correlation matrix from CorrelationInput model.
---

# compute_correlation_from_input

```python
def compute_correlation_from_input(inp: CorrelationInput) -> dict
```

Compute correlation matrix from CorrelationInput model.

Args:
    inp: CorrelationInput with price_data, method, and returns_based flag.

Returns:
    Dictionary with correlation matrix and metadata.
