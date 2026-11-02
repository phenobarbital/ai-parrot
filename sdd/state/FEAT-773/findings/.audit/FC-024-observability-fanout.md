---
id: FC-024
query_id: Q043
type: read
intent: "R4: read the FEAT-710 fan-out module — the established pattern for publishing lifecycle events on the bus."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-024 — observability/fanout.py shows the sanctioned publish pattern: dedicated EventBus(transport='streams', publish_only=True), validated, subscribed to lifecycle registry events, redacted payloads

## Summary

`parrot/observability/fanout.py` (147 lines). `setup_event_fanout(bus=None)` builds/validates a navigator-eventbus `EventBus` requiring `transport='streams'` and `publish_only=True` (`_validate_bus`), subscribes four lifecycle events from `get_global_registry()`, forwards redacted dicts (`FORWARD_DENYLIST={"error_message"}`), writes an outbox path fallback; `shutdown_event_fanout()`. 'ai-parrot only publishes; the consumer lives outside this package.'

## Citations

- path: `packages/ai-parrot/src/parrot/observability/fanout.py`
  lines: 1-5
  symbol: `module docstring`
  excerpt: |
    FEAT-710 — fan-out of the four usage lifecycle events to a durable EventBus. Native forward_to_bus on top of navigator-eventbus FEAT-711. ai-parrot only publishes
- path: `packages/ai-parrot/src/parrot/observability/fanout.py`
  lines: 74-87
  symbol: `_validate_bus`
  excerpt: |
    if transport != "streams" or publish_only is not True:
        raise RuntimeError("Event fan-out bus must use transport=streams and publish_only=True")
- path: `packages/ai-parrot/src/parrot/observability/fanout.py`
  lines: 90-121
  symbol: `setup_event_fanout`
  excerpt: |
    EventBus(transport="streams", publish_only=True, ...)

## Notes

Pattern to follow for `connection.*` events: Redis Streams, publish-only in parrot, consumers elsewhere. Note: a publish-only bus means in-process subscribers (Telegram notifier) would need a *separate* consuming bus instance.
