---
type: Wiki Entity
title: CostCalculator
id: class:parrot.observability.cost.calculator.CostCalculator
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Stateless USD cost calculator using bundled or overridden pricing tables.
---

# CostCalculator

Defined in [`parrot.observability.cost.calculator`](../summaries/mod:parrot.observability.cost.calculator.md).

```python
class CostCalculator
```

Stateless USD cost calculator using bundled or overridden pricing tables.

Pricing tables are loaded once at module level on first construction.
All subsequent constructions reuse the cached data — no filesystem I/O.

Args:
    override_path: Optional directory containing ``<provider>.json`` files
        that override bundled pricing via deep-merge (per-model granularity).
    stale_warn_days: Emit a WARN at boot for any provider file older than
        this many days. Default: 90.
    today: Reference date for staleness check. Defaults to ``date.today()``.
        Pass explicitly in tests to avoid time-dependent failures.

## Methods

- `def cost_usd(self, *, provider: str, model: str, input_tokens: int, output_tokens: int, cached_input_tokens: int=0) -> Optional[float]` — Compute USD cost for a single LLM API call.
