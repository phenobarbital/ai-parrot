---
type: Concept
title: compute_cvar()
id: func:parrot_tools.quant.risk_metrics.compute_cvar
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Conditional VaR (Expected Shortfall).
---

# compute_cvar

```python
def compute_cvar(returns: np.ndarray, confidence: float=0.95) -> float
```

Conditional VaR (Expected Shortfall).

Average of returns beyond the VaR threshold.
CVaR is always more conservative (more negative) than VaR.

Args:
    returns: Array of daily returns.
    confidence: Confidence level.

Returns:
    CVaR as a decimal (negative value indicates loss).
