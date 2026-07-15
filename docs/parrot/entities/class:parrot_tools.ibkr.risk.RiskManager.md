---
type: Wiki Entity
title: RiskManager
id: class:parrot_tools.ibkr.risk.RiskManager
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pre-trade risk management for IBKR orders.
---

# RiskManager

Defined in [`parrot_tools.ibkr.risk`](../summaries/mod:parrot_tools.ibkr.risk.md).

```python
class RiskManager
```

Pre-trade risk management for IBKR orders.

Runs configurable guardrails against incoming orders and returns
the first failure or an all-pass result. Tracks daily P&L for
loss-limit enforcement.

Args:
    config: Risk configuration with thresholds.
    confirmation_callback: Optional async callback invoked before
        order execution. Must return True to approve.

## Methods

- `async def validate_order(self, order: OrderRequest, current_positions: Optional[list[Position]]=None, current_price: Optional[Decimal]=None) -> RiskCheckResult` — Run all risk checks on an order.
- `def update_pnl(self, realized: Decimal=Decimal('0'), unrealized: Decimal=Decimal('0')) -> None` — Update daily P&L tracking.
- `def reset_daily_pnl(self) -> None` — Reset daily P&L counters (call at start of trading day).
