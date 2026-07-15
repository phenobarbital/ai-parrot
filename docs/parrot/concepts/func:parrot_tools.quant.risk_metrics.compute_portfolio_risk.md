---
type: Concept
title: compute_portfolio_risk()
id: func:parrot_tools.quant.risk_metrics.compute_portfolio_risk
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Compute all risk metrics for a portfolio.
---

# compute_portfolio_risk

```python
def compute_portfolio_risk(inp: PortfolioRiskInput) -> PortfolioRiskOutput
```

Compute all risk metrics for a portfolio.

Args:
    inp: PortfolioRiskInput with returns data, weights, and symbols.

Returns:
    PortfolioRiskOutput with all computed metrics.
