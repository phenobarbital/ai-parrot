---
id: F025
query_id: Q009
type: wiki_page
intent: "Orient: observability — OpenTelemetry spans, trace_id propagation, token usage / cost accounting."
executed_at: 2026-10-25T22:44:49Z
duration_ms: 0
parent_id: null
depth: 2
lane_origin: FW-010-observability-otel-usage
---

# F025 — Observability: GenAI-SemConv OTel spans, UsageRecord + CostCalculator per LLM call, ContextVar attribution (agent/run/seat); no cross-process trace propagation precedent

## Summary

`parrot.observability` (FEAT-177/462/228/479) provides `setup_telemetry(ObservabilityConfig)` with multi-endpoint OTLP export, `GenAIOpenTelemetrySubscriber` (spans), `MetricsSubscriber` (counters/histograms), `CostCalculator` (USD), a PII-free `UsageRecord` + pluggable recorders (`LoggingUsageRecorder`, `OpenLitUsageRecorder`), all driven by FEAT-176 lifecycle events; attribution via ContextVars `current_agent_name` (`agent_identity()`) and `current_run_id`/`current_seat` (`usage_attribution()`). This is the natural home for the brainstorm's "received" ledger and per-call cost (tokens, ms) on the calling side; a served-side deterministic call has no LLM event today, so a new tool/capability-level usage event would be needed. No page describes W3C traceparent extraction/injection across agents (A2A/MCP calls), so the "shared cross-boundary trace" is new. Ledger issue:9296682eda19 warns the env-driven auto-boot is dead code.

## Citations

- path: `packages/ai-parrot/src/parrot/observability/__init__.py`
  wiki_page_id: file:packages/ai-parrot/src/parrot/observability/__init__.py (score 0.63)
  excerpt: |
    ObservabilityConfig, OtlpTarget, setup_telemetry, shutdown_telemetry, ParrotTelemetryProvider,
    GenAIOpenTelemetrySubscriber, MetricsSubscriber, CostCalculator, UsageRecord, LoggingUsageRecorder, OpenLitUsageRecorder,
    current_agent_name, agent_identity, current_run_id, current_seat, usage_attribution
- path: `packages/ai-parrot/src/parrot/observability/subscribers/trace.py`
  symbol: `GenAIOpenTelemetrySubscriber`
  wiki_page_id: file:packages/ai-parrot/src/parrot/observability/subscribers/trace.py (score 0.30)
- path: `packages/ai-parrot/src/parrot/observability/recorders/openlit_recorder.py`
  symbol: `OpenLitUsageRecorder`
  wiki_page_id: file:packages/ai-parrot/src/parrot/observability/recorders/openlit_recorder.py (score 0.85)
  excerpt: |
    OpenLitUsageRecorder — pushes UsageRecords as GenAI SemConv OTel spans.
- path: `packages/ai-parrot/src/parrot/observability/setup.py`
  symbol: `setup_telemetry`
  wiki_page_id: file:packages/ai-parrot/src/parrot/observability/setup.py (score 0.81)
- path: `packages/ai-parrot/src/parrot/observability/cost.py`
  symbol: `ensure_shared_cost_calculator`
  excerpt: |
    from parrot.observability.cost import ensure_shared_cost_calculator   # used by fanout.py
- path: `packages/ai-parrot/src/parrot/observability/subscribers/metrics.py`
  wiki_page_id: file:packages/ai-parrot/src/parrot/observability/subscribers/metrics.py (score 0.36)

## Notes

- Ledger issue:1874ef259510 — usage.estimated_cost backfill not delivered (FEAT-710 follow-up); cost plumbing is still settling.
- `PermissionContext.trace_context` exists (FW-008) — a possible carrier for trace ids inside a request, but nothing documents it crossing a network hop.
- [cross-lane: type=grep, intent=grep "traceparent|inject(|extract(" in parrot/observability and parrot/a2a to confirm absence of cross-hop propagation]
