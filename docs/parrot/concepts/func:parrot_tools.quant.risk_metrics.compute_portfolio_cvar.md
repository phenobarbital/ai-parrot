---
type: Concept
title: compute_portfolio_cvar()
id: func:parrot_tools.quant.risk_metrics.compute_portfolio_cvar
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Portfolio CVaR (Expected Shortfall).
---

# compute_portfolio_cvar

```python
def compute_portfolio_cvar(returns_df: pd.DataFrame, weights: np.ndarray, confidence: float=0.95) -> float
```

Portfolio CVaR (Expected Shortfall).

Args:
    returns_df: DataFrame with asset returns.
    weights: Portfolio weights.
    confidence: Confidence level.

Returns:
    Portfolio CVaR as a decimal.
