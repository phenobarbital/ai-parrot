---
id: F003
query_id: Q008
type: grep
intent: Locate cost-tracking code — whether cost is computed in-process and emitted as a metric or must be derived in PromQL
executed_at: 2026-09-10T16:12:00Z
parent_id: F002
depth: 1
---

# F003 — Cost is computed in-process and emitted as a USD counter

## Summary

Cost does NOT have to be derived in PromQL from token counts and a price table.
`setup_telemetry` builds a `CostCalculator` when `enable_cost_tracking` is true
(env `OBSERVABILITY_COST`, currently `True`) and injects it into
`MetricsSubscriber`, which adds the computed USD onto the
`gen_ai.client.cost.total` counter with the full `{provider, model, agent}`
label set. A cost dashboard is therefore a direct `sum by (...)` over one
counter — no recording rules, no hardcoded prices in Grafana.

## Citations

- path: `packages/ai-parrot/src/parrot/observability/setup.py`
  lines: 213-232
  excerpt: |
    cost_calc = None
    if config.enable_cost_tracking:
        from parrot.observability.cost.calculator import CostCalculator
        ...
        cost_calc = CostCalculator(override_path=override)

- path: `packages/ai-parrot/src/parrot/observability/subscribers/metrics.py`
  lines: 246-258
  symbol: `MetricsSubscriber._on_client_after`
  excerpt: |
    if self._cost is not None:
        cost = self._cost.cost_usd(provider=system, model=event.model,
            input_tokens=event.input_tokens or 0, output_tokens=event.output_tokens or 0)
        if cost is not None:
            self._client_cost_total.add(cost, attributes=base)

- path: `packages/ai-parrot/src/parrot/observability/cost/pricing/README.md`

## Notes

`cost_usd()` returns `None` for an unpriced model — that call contributes zero
to the counter, silently. A dashboard should therefore show cost *and* request
count side by side so unpriced models are visible as "requests but no cost".
