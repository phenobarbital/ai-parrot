---
type: Wiki Entity
title: PortfolioRiskInput
id: class:parrot_tools.quant.models.PortfolioRiskInput
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Input for portfolio-level risk computation.
---

# PortfolioRiskInput

Defined in [`parrot_tools.quant.models`](../summaries/mod:parrot_tools.quant.models.md).

```python
class PortfolioRiskInput(BaseModel)
```

Input for portfolio-level risk computation.

Used by compute_portfolio_risk() to calculate VaR, CVaR, beta,
Sharpe ratio, and other portfolio-level metrics.

## Methods

- `def validate_weights(self) -> 'PortfolioRiskInput'` — Validate that weights sum to 1.0 and match symbols length.
