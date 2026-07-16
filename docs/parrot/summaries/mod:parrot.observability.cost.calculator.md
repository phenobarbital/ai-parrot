---
type: Wiki Summary
title: parrot.observability.cost.calculator
id: mod:parrot.observability.cost.calculator
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: CostCalculator — stateless USD cost estimation for LLM API calls.
relates_to:
- concept: class:parrot.observability.cost.calculator.CostCalculator
  rel: defines
---

# `parrot.observability.cost.calculator`

CostCalculator — stateless USD cost estimation for LLM API calls.

FEAT-177 TASK-1232.

Pricing tables are loaded from bundled JSON files once at first
``CostCalculator()`` construction and cached at module level. No filesystem
I/O occurs in the hot path (``cost_usd``).

Override path: ``ObservabilityConfig.pricing_override_path`` or
``PARROT_PRICING_PATH`` env var (resolved by ``setup_telemetry``).

Spec §3 Module 5, §8 D5 (bundled JSON, 90-day stale warning).

## Classes

- **`CostCalculator`** — Stateless USD cost calculator using bundled or overridden pricing tables.
