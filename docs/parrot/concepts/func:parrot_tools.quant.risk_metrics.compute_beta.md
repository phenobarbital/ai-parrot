---
type: Concept
title: compute_beta()
id: func:parrot_tools.quant.risk_metrics.compute_beta
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Beta = Cov(asset, benchmark) / Var(benchmark).
---

# compute_beta

```python
def compute_beta(asset_returns: np.ndarray, benchmark_returns: np.ndarray) -> float
```

Beta = Cov(asset, benchmark) / Var(benchmark).

Args:
    asset_returns: Asset daily returns.
    benchmark_returns: Benchmark daily returns.

Returns:
    Beta coefficient.

Raises:
    ValueError: If arrays have different lengths.
