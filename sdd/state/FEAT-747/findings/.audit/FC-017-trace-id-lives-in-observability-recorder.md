---
id: FC-017
query_id: Q043
type: grep
intent: "Trace / correlation propagation today (shared trace_id in parent envelope)."
executed_at: 2026-10-26T00:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-017 — trace_id lives in observability recorders and FlowContext; TraceContext class not in parrot src

## Summary

`trace_id|correlation_id|traceparent` over observability, bots, tools: `observability/recorders/{models(3),subscriber(4),openlit_recorder(2),prometheus_recorder(1),logging_recorder(1)}.py`, `observability/subscribers/trace.py` (1), `tools/executors/abstract.py` (1). `FlowContext.trace_context` carries a W3C `TraceContext` (FC-004) imported from `parrot.core.events.lifecycle`, but `grep 'class TraceContext'` over `packages/ai-parrot/src/parrot` finds **no definition** — it is re-exported from a dependency (likely navigator-eventbus/navigator-observability). Matrix tunnels use their own `correlation_id` futures (FC-008). An integration test `tests/integration/events/test_a2a_trace_propagation.py` already asserts trace propagation across an A2A hop.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/flows/core/context.py`
  lines: 112-119
  symbol: `FlowContext.trace_context`
  excerpt: |
    trace_context: Optional["TraceContext"] = field(default=None)
    """W3C TraceContext for this run (FEAT-176 Phase 1.5)."""

- path: `packages/ai-parrot/src/parrot/bots/flows/core/context.py`
  lines: 33-35
  symbol: `imports`
  excerpt: |
    from parrot.core.events.lifecycle import TraceContext

- path: `packages/ai-parrot/src/parrot/observability/recorders/models.py`
  lines: 1
  symbol: `module`
  excerpt: |
    trace_id fields on recorder models (3 hits)

- path: `packages/ai-parrot/src/parrot/observability/subscribers/trace.py`
  lines: 1
  symbol: `module`
  excerpt: |
    trace subscriber (1 hit)

- path: `packages/ai-parrot/tests/integration/events/test_a2a_trace_propagation.py`
  lines: 1
  symbol: `test module`
  excerpt: |
    asserts trace_id survives an A2A call


## Notes

grep budget exhausted before resolving where `TraceContext` is defined. `[cross-lane: type=wiki_query, intent=TraceContext definition and the lifecycle event envelope that carries trace_id — FW-013 may cover]`
