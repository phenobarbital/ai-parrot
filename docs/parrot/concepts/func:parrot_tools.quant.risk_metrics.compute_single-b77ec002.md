---
type: Concept
title: compute_single_asset_risk()
id: func:parrot_tools.quant.risk_metrics.compute_single_asset_risk
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Compute all risk metrics for a single asset.
---

# compute_single_asset_risk

```python
def compute_single_asset_risk(inp: AssetRiskInput) -> RiskMetricsOutput
```

Compute all risk metrics for a single asset.

Args:
    inp: AssetRiskInput with returns and optional benchmark.

Returns:
    RiskMetricsOutput with all computed metrics.
