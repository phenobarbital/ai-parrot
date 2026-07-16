# EventBus v2 — Unified Event Fabric (FEAT-310)

AI-Parrot's app-wide event fabric: one envelope contract, fire-and-forget
queued dispatch, severity-based alerting, pluggable transports, and
first-class ingress/egress adapters.

Spec: `sdd/specs/eventbus-v2.spec.md` · Config: [eventbus-config.md](eventbus-config.md) ·
Migration: [eventbus-migration.md](eventbus-migration.md)

## Architecture

```
                 ┌────────────────────────── INGRESS ──────────────────────────┐
  LifecycleEvent │ HookManager(route_to_bus)   WebSocketIngress   GrpcIngress  │
  (EventRegistry │        │ hooks.<type>.<event>      │ (BaseHook)   │(BaseHook)│
   dual-emit,    └────────┼───────────────────────────┼─────────────┼──────────┘
   unchanged)             ▼                           ▼             ▼
        │          ┌──────────────────────────────────────────────────┐
        └─────────▶│  EventBus facade (evb.py — legacy API preserved) │
                   │        Event ↔ EventEnvelope converters          │
                   └───────────────────────┬──────────────────────────┘
                                           ▼
                   ┌──────────────────────────────────────────────────┐
                   │ BusCore: per-priority asyncio.Queues → TaskGroup │
                   │ workers · glob matching · severity filters ·     │
                   │ retry/backoff · backpressure · meta-events       │
                   └───────┬──────────────────────────┬───────────────┘
                           ▼                          ▼
                ┌────────────────────┐      ┌─────────────────────────┐
                │ TransportBackend   │      │ EGRESS subscribers      │
                │ · MemoryBackend    │      │ · NotificationSubscriber│
                │ · RedisStreams     │      │   (async-notify)        │
                │ · RedisPubSub(leg.)│      │ · AuditSubscriber       │
                └────────────────────┘      │   (asyncdb)             │
                           │                │ · MetricsSubscriber     │
                           ▼                └─────────────────────────┘
                   bus.dlq (persisted, asyncdb — both modes)
```

## The four layers

### 1. Envelope (`parrot/core/events/bus/envelope.py`)

`EventEnvelope` is a **frozen, slotted dataclass** — the single closed
contract for "an event in Parrot". Fields: `topic`, `payload`, `event_id`,
tz-aware `timestamp` (naive → `ValueError`), `source`,
`severity: Severity`, `priority: EventPriority`, `correlation_id`,
`trace_context`, `metadata`.

- `Severity` (DEBUG/INFO/WARNING/ERROR/CRITICAL) is **orthogonal** to
  `EventPriority`: priority controls *scheduling*, severity controls
  *filtering and alerting*. Severity never affects dispatch order.
- Pydantic validation exists **only at ingress boundaries**
  (`IngressEnvelope`, `extra="forbid"`); the hot path stays dataclass-fast.
- Converters (`bus/converters.py`) map the three legacy shapes —
  `Event`, `LifecycleEvent.to_dict()`, `HookEvent` — into envelopes,
  coercing naive legacy timestamps to UTC.

### 2. Core dispatcher (`bus/core.py`)

`BusCore.publish()` is an **O(1) enqueue** into one `asyncio.Queue` per
priority; a bounded `asyncio.TaskGroup` worker pool drains CRITICAL before
LOW. Features:

- `subscribe(pattern, handler, *, priority=0, filter_fn=None, min_severity=None)`
  — glob/exact topics, severity floors.
- Per-handler `asyncio.timeout`; retry-with-backoff; exhausted retries hand
  the envelope to the DLQ hook.
- **Error isolation model B**: handler exceptions never reach the emitter;
  they surface as `bus.subscriber_error` meta-events with a contextvar
  recursion guard (same mechanism as `EventRegistry`).
- Backpressure per topic class: `block` (default, emits `bus.backpressure`),
  `drop_oldest`, `reject`.
- Graceful `close()`: rejects new publishes, drains with a deadline.

Benchmark evidence (`artifacts/logs/feat-310-bench-*.txt`): `emit()` p99
≈ 57 µs — 35× under the FEAT-177 budget (0.1% of a 2 s LLM call = 2 ms).

### 3. Transport backends (`bus/backends/`)

Small `TransportBackend` protocol (`publish` / `start_consumer` / `close`);
wire format is `EventEnvelope.to_dict()` JSON everywhere.

| Backend | Semantics | Use |
|---|---|---|
| `MemoryBackend` | in-process, at-most-once | default |
| `RedisPubSubBackend` | fan-out only, at-most-once, unpersisted | legacy interop (`parrot:events:*` channels) |
| `RedisStreamsBackend` | **durable at-least-once**: consumer groups, `XACK`, `XAUTOCLAIM` sweeper, `event_id` TTL dedup | distributed (Cloud Run) |

⚠️ Streams mode is at-least-once, NOT exactly-once — the dedup set
mitigates duplicates but cannot eliminate them. **Consumers must be
idempotent in distributed mode.** Retention: `XADD … MAXLEN ~ 100000`
per stream (`parrot:stream:<topic-class>`).

### 4. Ingress / egress

- **Hooks** (`HookManager`): legacy dual-emit unchanged; the FEAT-310
  `route_to_bus` mode publishes first-class `hooks.<type>.<event>`
  envelopes. The orchestrator direct callback is KEPT permanently.
- **`WebSocketIngress` / `GrpcIngress`** (`bus/ingress/`): `BaseHook`
  adapters validating ALL external input at the `IngressEnvelope`
  boundary. gRPC ships as optional extra `ai-parrot[grpc]`
  (`parrot.events.v1`, A2UI-style versioned messages).
- **Egress subscribers** (`bus/subscribers/`): `NotificationSubscriber`
  (severity alerting via async-notify with dedup/throttle/storm-guard),
  `AuditSubscriber` (append-only `navigator.evb_audit`),
  `MetricsSubscriber` (`snapshot()` counters + latency buckets).
- **DLQ** (`bus/dlq.py`): retry-exhausted envelopes republish on `bus.dlq`
  and persist to `navigator.evb_dlq` (asyncdb `pg`) in BOTH memory and
  Streams modes; `replay()` re-publishes to original topics.

## Doctrine: typed hot path vs app-wide fabric

Parrot has **two subscription systems, coexisting BY DESIGN** — do not
consolidate them:

| | `EventRegistry` (typed hot path) | Topic bus (app-wide fabric) |
|---|---|---|
| Contract | frozen `LifecycleEvent` subclasses | `EventEnvelope` topics |
| Matching | `isinstance` | glob patterns |
| Serialization | none (in-process objects) | JSON-safe dicts |
| Latency budget | agent-request path (FEAT-177) | queued, asynchronous |
| Use for | agent/client/tool lifecycle observability | cross-component app events, hooks, alerting, audit |

The registry's per-subscriber `forward_to_bus=True` bridges the two: the
typed event's dict form is dual-emitted onto the bus **fire-and-forget**
(the agent path never waits for the bus).

## Meta-topics

| Topic | Meaning | Severity |
|---|---|---|
| `bus.subscriber_error` | a handler exhausted its retries | INFO |
| `bus.backpressure` | a backpressure policy activated | INFO |
| `bus.dlq` | terminal topic for dead-lettered envelopes | WARNING |
| `bus.dlq_error` | DLQ persistence itself failed | WARNING |

Internal `bus.*` topics are capped below the default alert threshold and
excluded from alerting/audit by default — this prevents
`dlq → notify → error → dlq` loops.
