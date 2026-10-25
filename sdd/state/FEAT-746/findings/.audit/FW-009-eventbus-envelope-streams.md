---
id: FW-009
query_id: Q008
type: wiki_page
intent: "Orient: navigator-eventbus usage inside parrot (publish/subscribe, correlation)."
executed_at: 2026-10-25T22:44:49Z
duration_ms: 0
parent_id: null
depth: 2
---

# FW-009 — EventBus v2 (navigator-eventbus): frozen EventEnvelope with correlation_id/trace_context, Redis Streams at-least-once + dedup + DLQ; gRPC/WS ingress exist as adapters; no request/reply (reply_to) RPC pattern

## Summary

The bus core was extracted to the external `navigator-eventbus` package (TASK-1827 deleted `evb.py`/`bus/` from parrot; TASK-1826 added the dependency). The contract documented in `docs/events/eventbus-v2.md`: `EventEnvelope` (frozen dataclass: topic, payload, event_id, tz-aware timestamp, source, severity, priority, **correlation_id, trace_context**, metadata), `BusCore.publish()` O(1) enqueue, backends Memory / RedisPubSub (legacy) / **RedisStreams (durable at-least-once, consumer groups, XACK, XAUTOCLAIM, event_id TTL dedup)**, DLQ persisted to `navigator.evb_dlq` with `replay()`, `AuditSubscriber` (append-only `navigator.evb_audit`), and `WebSocketIngress`/`GrpcIngress` (`parrot.events.v1` proto, optional `[grpc]` extra, bearer token in RPC metadata). Parrot today only *publishes* usage lifecycle events: `observability/fanout.py` (FEAT-710, 2026-10-25) requires `EventBus(transport="streams", publish_only=True, outbox=...)`. Wire format is JSON (`EventEnvelope.to_dict()`), and no `reply_to`/request-response convention is described — brainstorm VERIFY "RPC-on-bus pattern is not defined" holds, while idempotency/dedup/DLQ primitives for the bus carrier already exist.

## Citations

- path: `docs/events/eventbus-v2.md`
  wiki_page_id: file:docs/events/eventbus-v2.md (score 0.42)
  excerpt: |
    EventEnvelope fields: topic, payload, event_id, timestamp, source, severity, priority, correlation_id, trace_context, metadata
    RedisStreamsBackend — durable at-least-once: consumer groups, XACK, XAUTOCLAIM sweeper, event_id TTL dedup
    WebSocketIngress / GrpcIngress (bus/ingress/) ... gRPC ships as optional extra ai-parrot[grpc] (parrot.events.v1)
- path: `packages/ai-parrot/src/parrot/observability/fanout.py`
  symbol: `setup_event_fanout`
  wiki_page_id: file:packages/ai-parrot/src/parrot/observability/fanout.py (score 1.00; ingested 2026-10-25)
  excerpt: |
    from navigator_eventbus import EventBus
    bus = EventBus(redis_url=..., transport="streams", publish_only=True, channel_prefix="parrot:events:", outbox=_outbox_path())
    registry.attach_bus(bus, serializer=redact_usage_event); registry.subscribe(event_cls, _noop, forward_to_bus=True)
- path: `sdd/tasks/completed/TASK-1827-delete-rewire-events-bus-core.md`
  wiki_page_id: file:sdd/tasks/completed/TASK-1827-delete-rewire-events-bus-core.md (score 0.43)
  excerpt: |
    Delete bus core (evb.py + bus/) and minimize events/__init__.py   (bus now lives in navigator-eventbus)
- path: `sdd/tasks/completed/TASK-1804-ingress-ws-grpc.md`
  wiki_page_id: file:sdd/tasks/completed/TASK-1804-ingress-ws-grpc.md (score 0.91)
  excerpt: |
    Mudar ingress WebSocket y gRPC (+ proto package fix)  — ingress adapters moved with the bus
- path: `packages/ai-parrot/src/parrot/core/events/lifecycle/events.py`
  symbol: `AfterClientCallEvent`
  excerpt: |
    AfterInvokeEvent, InvokeFailedEvent, AfterClientCallEvent, ClientCallFailedEvent  (typed hot-path events; forward_to_bus bridge)
- path: `docs/events/eventbus-migration.md`
  wiki_page_id: file:docs/events/eventbus-migration.md (score 0.93)

## Notes

- Doctrine in the doc: two subscription systems by design — typed `EventRegistry` hot path vs topic bus. A call/result envelope on the bus would be a topic-bus citizen, serialized JSON today (binary payloads would need a bytes-safe serializer on the backend).
- Grep in packages/*/src found no `GrpcIngress` / `parrot.events.v1` — confirms they live in navigator-eventbus now.
- [cross-lane: type=grep, intent=grep navigator_eventbus usages beyond fanout.py (subscribers/consumers) to see whether parrot consumes anything from the bus today]
