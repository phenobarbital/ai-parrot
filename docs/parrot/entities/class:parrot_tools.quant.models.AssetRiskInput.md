---
type: Wiki Entity
title: AssetRiskInput
id: class:parrot_tools.quant.models.AssetRiskInput
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Input for single-asset risk metrics.
---

# AssetRiskInput

Defined in [`parrot_tools.quant.models`](../summaries/mod:parrot_tools.quant.models.md).

```python
class AssetRiskInput(BaseModel)
```

Input for single-asset risk metrics.

Used by compute_risk_metrics() to calculate VaR, CVaR, beta,
Sharpe ratio, and maximum drawdown for a single asset.
