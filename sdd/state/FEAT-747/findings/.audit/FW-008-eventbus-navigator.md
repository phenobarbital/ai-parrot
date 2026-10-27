---
id: FW-008
query_id: Q007
type: wiki_query
intent: "Orient: navigator-eventbus usage inside ai-parrot (default carrier candidate)."
executed_at: 2026-10-25T22:46:00Z
duration_ms: 900
parent_id: null
depth: 0
---

# FW-008 — navigator-eventbus is already a dependency: EventBus v2 (FEAT-310) with BusCore/DLQ, Streams publish-only fan-out (FEAT-710), HookManager route_to_bus, and MatrixHook as a bus hook

## Summary

The default-carrier candidate is already integrated. `observability/fanout.py` (FEAT-710) does `from navigator_eventbus import EventBus`, validates a **Streams transport in publish-only mode** (`_validate_bus`), has a durable **outbox** (`_outbox_path`) and `setup_event_fanout(bus)` / `shutdown_event_fanout()`; it forwards four lifecycle events (`AfterInvokeEvent, InvokeFailedEvent, AfterClientCallEvent, ClientCallFailedEvent`) with a redaction denylist. EventBus v2 (FEAT-310: `docs/events/eventbus-v2.md`, `docs/events/eventbus-migration.md`) introduced `BusCore` (queued dispatch, worker pool, severity filters, retry, backpressure — TASK-1784), an `EventBus` facade preserving the legacy API (TASK-1786), converters + **DLQ** + ingress models (TASK-1800), and `HookManager.route_to_bus` tri-state auto-routing (TASK-1790/1841); navigator-eventbus 0.1.0 was released as its own package (TASK-1842). Specs: `sdd/specs/eventbus-consolidation.spec.md`, `eventbus-core-extraction.spec.md`, `eventbus-lifecycle-extraction.spec.md`, `eventbus-v2.spec.md`. `MatrixHook` itself subclasses `navigator_eventbus.hooks.base.BaseHook` (FW-005). The parent brainstorm's VERIFY 'the RPC-on-bus pattern (reply_to, correlation) is not defined' is plausible — nothing surfaced names `reply_to`/`correlation_id` on the bus — but the bus, DLQ and durable outbox the sister spec wants to reuse exist.

## Citations

- path: `packages/ai-parrot/src/parrot/observability/fanout.py`
  lines: 1-45
  symbol: `setup_event_fanout / _validate_bus / redact_usage_event`
  wiki_page_id: file:packages/ai-parrot/src/parrot/observability/fanout.py (score=1.00)
  excerpt: |
    from navigator_eventbus import EventBus
    def _validate_bus(bus): Require a Streams transport configured in publish-only mode.
    def setup_event_fanout(bus): Attach a dedicated Streams/publish-only bus and subscribe usage events.
    FORWARDED_EVENTS = (AfterInvokeEvent, InvokeFailedEvent, AfterClientCallEvent, ClientCallFailedEvent)
- path: `docs/events/eventbus-v2.md`
  lines: n/a
  symbol: `EventBus v2 — Unified Event Fabric (FEAT-310)`
  wiki_page_id: file:docs/events/eventbus-v2.md (score=0.42)
- path: `docs/events/eventbus-migration.md`
  lines: n/a
  symbol: `EventBus v2 Migration Notes`
  wiki_page_id: file:docs/events/eventbus-migration.md (score=0.93)
- path: `sdd/tasks/completed/TASK-1800-buscore-facade-dlq.md`
  lines: n/a
  symbol: `BusCore facade, converters, DLQ, ingress models`
  wiki_page_id: file:sdd/tasks/completed/TASK-1800-buscore-facade-dlq.md (score=0.81)
- path: `sdd/specs/eventbus-consolidation.spec.md`
  lines: n/a
  symbol: `eventbus consolidation spec`
  wiki_page_id: file:sdd/specs/eventbus-consolidation.spec.md (score=0.47)
- path: `packages/ai-parrot/tests/unit/events/lifecycle/test_registry.py`
  lines: n/a
  symbol: `EventRegistry dispatch tests`
  wiki_page_id: file:packages/ai-parrot/tests/unit/events/lifecycle/test_registry.py (score=0.78)

## Notes

Ledger issue 9296682eda19 notes observability auto-boot is dead (`set_bootstrap_hook` never installed) — fan-out may not be live in production. `[cross-lane: type=grep, intent=reply_to|correlation_id|idempotency in navigator_eventbus usage and parrot/core/events]`.
