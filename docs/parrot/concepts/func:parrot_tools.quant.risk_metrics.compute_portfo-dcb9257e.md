---
type: Concept
title: compute_portfolio_var_historical()
id: func:parrot_tools.quant.risk_metrics.compute_portfolio_var_historical
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Portfolio VaR using historical simulation.
---

# compute_portfolio_var_historical

```python
def compute_portfolio_var_historical(returns_df: pd.DataFrame, weights: np.ndarray, confidence: float=0.95) -> float
```

Portfolio VaR using historical simulation.

Computes portfolio returns for each day and takes the empirical percentile.

Args:
    returns_df: DataFrame with asset returns.
    weights: Portfolio weights.
    confidence: Confidence level.

Returns:
    Portfolio VaR as a decimal.
