---
type: Concept
title: compute_portfolio_var_parametric()
id: func:parrot_tools.quant.risk_metrics.compute_portfolio_var_parametric
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Portfolio VaR using variance-covariance method.
---

# compute_portfolio_var_parametric

```python
def compute_portfolio_var_parametric(returns_df: pd.DataFrame, weights: np.ndarray, confidence: float=0.95) -> float
```

Portfolio VaR using variance-covariance method.

portfolio_var = z * sqrt(w' * Cov * w)

Args:
    returns_df: DataFrame with asset returns (columns are assets).
    weights: Portfolio weights.
    confidence: Confidence level.

Returns:
    Portfolio VaR as a decimal.
