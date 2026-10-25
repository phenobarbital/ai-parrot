---
id: F018
query_id: Q056
type: git_log
intent: "Recent history: observability (tracing, usage)."
executed_at: 2026-10-25T22:41:57Z
duration_ms: 350
parent_id: null
depth: 0
lane_origin: FG-006-observability-history
---

# F018 — observability history: telemetry event fan-out with per-call cost_usd and tenant/user/session landed Oct 2026

## Summary

15 commits in 120 days on `parrot/observability/`, concentrated 2026-10-19/22: FEAT-705 (metrics fan-out + env config) and FEAT-710 parrot-telemetry-event-fanout (10/10 done): tenant ContextVar bound on every ask(), tenant/user/session/cost_usd on the four usage events, a process-wide shared CostCalculator, cost filled at the AbstractClient emit sites, subscribers consume event.cost_usd, fan-out wiring `attach_bus` + `forward_to_bus` over durable Streams, fail-loud auto-boot. Per-call cost accounting (D12) and a bus-connected telemetry pipeline (D13 "served" ledger inputs) therefore already exist on the LLM-call side; what is missing is a cross-boundary trace joining two agents.

## Citations

- path: `packages/ai-parrot/src/parrot/observability/`
  commit: `9b08af6b6` 2026-10-22 Jesus — feat(parrot-telemetry-event-fanout): TASK-4548 — backfill usage.estimated_cost from the origin cost (AC-3)
- path: `packages/ai-parrot/src/parrot/observability/`
  commit: `9001863a9` 2026-10-22 Jesus — feat(parrot-telemetry-event-fanout): TASK-4550 — Subscribers consume event.cost_usd (single cost computation)
- path: `packages/ai-parrot/src/parrot/observability/`
  commit: `ba4bffbb7` 2026-10-22 Jesus — feat(parrot-telemetry-event-fanout): TASK-4553 — engine-committed coder deliverable (event fan-out wiring: attach_bus + forward_to_bus over durable Streams)
- path: `packages/ai-parrot/src/parrot/observability/`
  commit: `5843d689e` 2026-10-22 Jesus — feat(parrot-telemetry-event-fanout): TASK-4547 — process-wide shared CostCalculator + resolve_event_cost helper
- path: `packages/ai-parrot/src/parrot/observability/`
  commit: `4530ad5a4` 2026-10-19 Jesus Lara — feat(observability-metrics-fanout-and-env-config): TASK-4483 — engine-committed coder deliverable
- path: `sdd/tasks/index/parrot-telemetry-event-fanout.json`
  symbol: FEAT-710
  excerpt: |
    completed_at 2026-10-22; 10/10 done — TASK-4544 current_tenant ContextVar, TASK-4546 tenant/user/
    session/cost_usd on usage events, TASK-4547 shared CostCalculator, TASK-4553 attach_bus + forward_to_bus
- path: `packages/ai-parrot/src/parrot/core/events/lifecycle/subscribers/opentelemetry.py`
  excerpt: |
    (file exists on dev — an OpenTelemetry subscriber for lifecycle events)

## Notes

[cross-lane: type=read, intent=read parrot/core/events/lifecycle/subscribers/opentelemetry.py and the usage event models to see whether a trace_id/correlation field already exists on events]
