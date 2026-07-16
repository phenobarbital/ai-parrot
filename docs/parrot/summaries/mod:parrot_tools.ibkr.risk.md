---
type: Wiki Summary
title: parrot_tools.ibkr.risk
id: mod:parrot_tools.ibkr.risk
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pre-trade risk management for IBKR agent-driven trading.
relates_to:
- concept: class:parrot_tools.ibkr.risk.RiskCheckResult
  rel: defines
- concept: class:parrot_tools.ibkr.risk.RiskManager
  rel: defines
- concept: mod:parrot_tools.ibkr.models
  rel: references
---

# `parrot_tools.ibkr.risk`

Pre-trade risk management for IBKR agent-driven trading.

Implements configurable guardrails that intercept order operations before
they reach the backend. All monetary comparisons use Decimal arithmetic.

## Classes

- **`RiskCheckResult(BaseModel)`** — Result of a risk check.
- **`RiskManager`** — Pre-trade risk management for IBKR orders.
