# EventBus v2 Migration Notes (FEAT-310)

The `EventBus` public API is **preserved verbatim** — `emit`, `subscribe`,
`on`, `publish`, `unsubscribe`, `connect`, `close`, plus the four exports
`EventBus`, `Event`, `EventPriority`, `EventSubscription`. Existing call
sites (`EventRegistry.forward_to_bus`, `HookManager.set_event_bus`,
`AutonomousOrchestrator`, `EvalRunner`, `AbstractBot`, `WebhookListener`)
need **zero changes**.

That said, three semantics shifted:

## 1. Delivery is asynchronous now

Before: `await bus.publish(event)` awaited every handler **sequentially**
— a slow handler stalled the emitter and all sibling subscribers.

After: `publish()`/`emit()` are an O(1) enqueue; handlers run on a bounded
worker pool. The emitter returns in ~tens of microseconds
(`artifacts/logs/feat-310-bench-*.txt`).

**Implication:** code that assumed handlers had already run when
`publish()` returned must not — await your own coordination primitive
(event/future) from inside the handler if you need completion signals.

## 2. The return count means "matched", not "handled"

`publish()`/`emit()` still return an `int`, but it is now the number of
subscribers **matched at enqueue time**. Delivery (including retries and
DLQ) happens later on the workers.

## 3. Handler failures no longer just log

Handler exceptions were swallowed with a log line. Now each handler gets
`BUS_RETRY_ATTEMPTS` tries with backoff and a per-attempt timeout; final
failures emit `bus.subscriber_error` meta-events and dead-letter the
envelope to `bus.dlq` (persisted in `navigator.evb_dlq` when a Postgres
DSN is configured). Replay with `DLQHandler.replay()`.

## Smaller changes

- **`Event.timestamp` default is now tz-aware UTC** (was naive
  `datetime.now()`). `Event.from_dict()` fallback likewise. Naive
  timestamps from external/legacy sources are still accepted and coerced
  to UTC by the converters.
- **`start_redis_listener()` is a deprecated no-op alias** — the Redis
  consumer starts automatically with the bus. Calling it just logs a
  deprecation warning (safe for the orchestrator's `create_task`).
- **Redis wire format changed** for bus-to-bus traffic: envelope
  `to_dict()` JSON (with `topic`) instead of the legacy `Event` dict (with
  `event_type`). Channels keep the `parrot:events:` prefix, but old and
  new processes should not consume each other's messages during a rolling
  deploy — upgrade producers and consumers together, or run Streams mode.
- **`_event_history` is a bounded `deque(maxlen=1000)`** (was a manually
  trimmed list). Same practical behavior.
- **New additive kwargs** (optional): `emit(..., severity=Severity.ERROR)`
  / `publish(event, severity=...)` and
  `subscribe(..., min_severity=Severity.WARNING)`.
- **Publishing after `close()` raises `BusClosedError`** (was silently
  accepted).

## New capabilities you can opt into

| Capability | How |
|---|---|
| Durable at-least-once distributed mode | `BusCore(backend=RedisStreamsBackend(url))` |
| Severity alerting (email/Slack/Telegram/Teams) | `NotificationSubscriber` — see [eventbus-config.md](eventbus-config.md) |
| Hooks as first-class bus topics | `HookManager(route_to_bus=True)` |
| WebSocket / gRPC ingress | `WebSocketIngress`, `GrpcIngress` (`pip install ai-parrot[grpc]`) |
| Audit trail + metrics | `AuditSubscriber`, `MetricsSubscriber.snapshot()` |

## Running the tests

```bash
pytest packages/ai-parrot/tests/core/events/ packages/ai-parrot/tests/core/hooks/ -v
# Redis-backed at-least-once test (needs a reachable Redis):
REDIS_TEST_URL=redis://localhost:6379/9 pytest -m integration \
  packages/ai-parrot/tests/core/events/bus/test_redis_streams.py -v
```
