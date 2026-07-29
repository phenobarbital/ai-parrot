---
type: Concept
title: compute_exposure()
id: func:parrot_tools.quant.risk_metrics.compute_exposure
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Compute net and gross exposure from weights.
---

# compute_exposure

```python
def compute_exposure(weights: list[float]) -> dict[str, float]
```

Compute net and gross exposure from weights.

Args:
    weights: List of position weights (negative for short).

Returns:
    Dictionary with net_exposure and gross_exposure.
