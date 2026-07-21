---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Unified EventBus v2 — queue-based dispatch, severity, ingress channels, and notifications

**Feature ID**: FEAT-310
**Date**: 2026-07-16
**Author**: Jesus (phenobarbital) + Claude
**Status**: approved
**Target version**: 0.26.0 (current: 0.25.18)
**Brainstorm**: `sdd/proposals/eventbus-v2.brainstorm.md` (Recommended Option B)

---

## 1. Motivation & Business Requirements

### Problem Statement

ai-parrot currently has **three parallel, weakly-integrated event subsystems**:

1. `parrot/core/events/evb.py` — a string-topic glob pub/sub `EventBus` (in-memory + optional Redis pub/sub).
2. `parrot/core/events/lifecycle/` (FEAT-176) — typed frozen `LifecycleEvent` dataclasses dispatched by `EventRegistry` (isinstance matching, error isolation model B, OTel/logging/webhook subscribers).
3. `parrot/core/hooks/` — external ingestion (Jira/GitHub webhooks, IMAP, Redis/RabbitMQ/MQTT/SQS brokers, scheduler, file watchers) whose events flow to an **orchestrator callback**, with the bus as an optional secondary dual-emit.

Consequences:

- **Three incompatible envelopes**: `Event` (mutable dataclass), `LifecycleEvent` (frozen dataclass + `TraceContext`), `HookEvent` (Pydantic BaseModel). No single closed contract for "an event in Parrot".
- **`EventBus.publish()` is NOT fire-and-forget**: handlers are `await`ed sequentially → head-of-line blocking; a slow handler stalls the emitter and all other subscribers. No internal queue, no worker pool, no backpressure. `EventPriority` only sorts the subscriber list; it does not influence scheduling.
- **Redis pub/sub is at-most-once and unpersisted**: crashed consumers lose events; no Redis Streams, consumer groups, ACKs, retries, DLQ, or durable replay (`_event_history` is a local Python list with O(n) slicing).
- **No severity model**: no DEBUG/INFO/WARNING/ERROR/CRITICAL on events, hence no severity-filtered subscriptions and no alerting/notification pipeline.
- **No gRPC / WebSocket ingress**, and existing HTTP ingress (hooks) does not feed the bus by default.
- **Duplicated dispatch logic**: `start_redis_listener()` re-implements `publish()`'s matching/dispatch inline and consumes messages sequentially inside the `async for`.
- Minor defects: naive `datetime.now()` in `Event` (evb.py:29) vs `timezone.utc` in `LifecycleEvent`; `event_id` exists but nothing deduplicates on it.

Affected: the autonomy/orchestrator layer, agent lifecycle observability, all hook-driven flows, and any future feature (alerting, audit, metrics) that needs a reliable in-app event fabric.

### Goals

- **G1 — One envelope**: a single frozen `EventEnvelope` contract with converters from `LifecycleEvent` and `HookEvent`; one wire format for the whole app.
- **G2 — Fire-and-forget publish**: `publish()`/`emit()` become O(1) enqueue; handlers run on a bounded worker pool; emitter-side latency honors the FEAT-177 budget (< 0.1% LLM-latency overhead).
- **G3 — Severity model + alerting**: `Severity` enum orthogonal to `EventPriority`; severity-filtered subscriptions; `NotificationSubscriber` delivering alerts through `parrot.notifications` (async-notify) channels, with rate-limiting/dedup defaults.
- **G4 — Durable distributed mode**: `RedisStreamsBackend` (consumer groups, ACK, `XAUTOCLAIM`, `event_id` dedup) providing at-least-once delivery across Cloud Run instances with zero app-code change.
- **G5 — Ingress unification**: hooks publish to `hooks.<type>.<event>` topics by default (`route_to_bus`); new WebSocket and gRPC ingress adapters on the `BaseHook` contract.
- **G6 — Non-breaking migration**: `EventBus.emit/subscribe/on/publish` signatures preserved; `events/__init__` keeps exporting all four names (`EventBus`, `Event`, `EventPriority`, `EventSubscription`); `EventRegistry.forward_to_bus` and `HookManager.set_event_bus` untouched.
- **G7 — Reliability semantics**: per-topic-class backpressure policy, retry-with-backoff, DLQ persisted via asyncdb in **both** memory and Streams modes, error isolation model B everywhere.

### Non-Goals (explicitly out of scope)

- Replacing the typed `EventRegistry` — typed lifecycle events remain the agent hot path (isinstance dispatch, zero serialization); the topic bus is the app-wide fabric. Two subscription systems coexist **by design**.
- Deprecating the orchestrator direct callback (`HookManager.set_event_callback`) — *resolved in brainstorm: keep it* as a permanent low-latency path.
- Adopting an external event framework (FastStream/nats-py) — rejected in brainstorm (Option C, see `sdd/proposals/eventbus-v2.brainstorm.md`).
- Incremental patching of `evb.py` without unifying envelopes — rejected in brainstorm (Option A).
- RabbitMQ/NATS transport backends — the backend protocol must allow them as future drop-ins, but only Memory and Redis (Streams + legacy pub/sub) backends ship in this feature.
- Fixing `close()`/`punsubscribe()` — already fixed on `dev` (evb.py:124).

---

## 2. Architectural Design

### Overview

New package `parrot/core/events/bus/` with four layers; existing subsystems are refitted as adapters (brainstorm Option B):

1. **Envelope** — frozen dataclass `EventEnvelope` (topic, payload, `event_id`, tz-aware timestamp, `source`, `severity: Severity`, `priority: EventPriority`, `correlation_id`, optional `trace_context`, `metadata`). *Resolved in brainstorm*: frozen dataclass core (consistent with `LifecycleEvent`, ~5x faster than Pydantic on hot paths) + **Pydantic model only at ingress boundaries** (`IngressEnvelope` validating external input in WS/gRPC/HTTP adapters, then converted to the dataclass). Thin converters map `LifecycleEvent.to_dict()` and `HookEvent` into envelopes. Constructor rejects naive datetimes.
2. **Core dispatcher** — `publish()` = O(1) enqueue into per-priority `asyncio.Queue`s drained by a bounded worker pool (`asyncio.TaskGroup`); explicit backpressure policy per topic class (`block` default / `drop_oldest` / `reject`); handler exceptions isolated (model B) and re-emitted as `bus.subscriber_error` meta-events with a contextvar recursion guard (same pattern as `EventRegistry`); retry-with-backoff; DLQ terminal topic `bus.dlq` **persisted via asyncdb in both modes** (*resolved in brainstorm*).
3. **Transport backends (pluggable)** — small `TransportBackend` protocol; `MemoryBackend` (default, at-most-once by config), `RedisStreamsBackend` (`XADD`/`XREADGROUP` + consumer groups + `XACK` + `XAUTOCLAIM` sweeper → at-least-once, durable, replayable; `event_id` dedup via TTL'd Redis set), legacy `RedisPubSubBackend` retained for fan-out-only cases.
4. **Ingress/egress adapters** —
   - *Ingress*: `HookManager.route_to_bus` mode (hooks publish `hooks.<type>.<event>` envelopes; the orchestrator callback **remains as-is** — *resolved in brainstorm: keep it*); new `WebSocketIngress` (aiohttp) and `GrpcIngress` (optional extra `parrot[grpc]`) implementing the `BaseHook` start/stop contract. gRPC proto **re-uses A2UI envelope ideas** (*resolved in brainstorm*) — mirror the `A2UIMessageBase` versioned-message shape from `parrot/outputs/a2ui/models.py` for `parrot.events.v1.PublishRequest`.
   - *Egress*: `NotificationSubscriber` — subscribes with `severity >= threshold` or sliding-window rate rules, delivers via **`parrot.notifications.NotificationMixin.send_notification()`** (async-notify: email/Slack/Telegram/Teams). ⚠️ Corrected from brainstorm: `hooks/messaging.py` is inbound-only (webhook receivers), NOT an outbound channel. `AuditSubscriber` (asyncdb append-only) and a metrics subscriber (counters/latency) alongside the existing OTel lifecycle subscriber.

**Facade**: `EventBus` (evb.py) becomes a facade over the core with its current public signature preserved; legacy `Event` ↔ `EventEnvelope` conversion is internal. `EventRegistry.forward_to_bus` and `HookManager.set_event_bus` keep working untouched (they call `emit(channel, dict)`).

**Notification rate-limiting defaults** (*resolved in brainstorm: Claude proposes, user accepted delegation*):
- Dedup window: identical `(rule_id, topic_class)` alerts suppressed for **300 s** after first delivery (repeat count appended on window close).
- Global throttle: max **10 notifications/min** per channel; overflow folded into a single digest message.
- Cascading-failure guard: if > **25 ERROR+ events / 30 s**, collapse into one CRITICAL "event storm" alert until the rate drops.
All three knobs configurable under `[bus.alerts]`.

### Component Diagram

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

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/core/events/evb.py` | modifies (becomes facade) | public API + all four `__init__` exports preserved; internals delegate to BusCore |
| `parrot/core/events/lifecycle/registry.py` | depends on | `forward_to_bus` path unchanged; still calls `emit(channel, dict)` fire-and-forget |
| `parrot/core/hooks/manager.py` | extends | new `route_to_bus` mode; `set_event_bus` semantics widened; orchestrator callback kept |
| `parrot/notifications` (`NotificationMixin`) | uses | outbound delivery layer for `NotificationSubscriber` (async-notify) |
| `parrot/core/hooks/base.py` (`BaseHook`) | implements | WS/gRPC ingress adapters follow start/stop + `setup_routes` contract |
| `parrot/core/hooks/brokers/base.py` | pattern reference | consumer-task lifecycle (`_run_consumer`) for Streams consumer loop |
| `AutonomousOrchestrator` | modifies (flagged) | sole `EventBus()` construction site (orchestrator.py:231); `_handle_hook_event` optionally re-registered as bus subscriber behind a flag |
| `parrot/eval/runner.py`, `AbstractBot`, `WebhookListener` | unchanged | injection sites — work as-is since facade preserves signatures |
| navconfig / TOML | extends | `[bus]`, `[[bus.alerts]]` config sections |
| asyncdb | uses | DLQ persistence + `AuditSubscriber` append-only store |
| Deployment (Cloud Run) | depends on | Streams requires reachable Memorystore/Upstash; per-instance consumer names |

### Data Models

```python
# parrot/core/events/bus/envelope.py — core contract (frozen dataclass, NOT Pydantic)
class Severity(IntEnum):            # log-level semantics — orthogonal to EventPriority
    DEBUG = 10; INFO = 20; WARNING = 30; ERROR = 40; CRITICAL = 50

@dataclass(frozen=True, slots=True)
class EventEnvelope:
    topic: str                       # "order.created", "hooks.webhook.jira", "bus.dlq"
    payload: dict[str, Any]
    event_id: str                    # uuid4; dedup key in at-least-once mode
    timestamp: datetime              # MUST be tz-aware; naive → ValueError
    source: str | None
    severity: Severity               # filtering/alerting
    priority: EventPriority          # dispatch scheduling (existing enum, reused)
    correlation_id: str | None
    trace_context: dict | None       # from LifecycleEvent.TraceContext when converted
    metadata: dict[str, Any]

# parrot/core/events/bus/ingress_models.py — Pydantic ONLY at ingress boundaries
class IngressEnvelope(BaseModel):    # model_config = ConfigDict(extra="forbid", frozen=True)
    ...                              # validates external WS/gRPC/HTTP input → to_envelope()
```

### New Public Interfaces

```python
# parrot/core/events/bus/core.py
class BusCore:
    async def publish(self, envelope: EventEnvelope) -> None      # O(1) enqueue
    def subscribe(self, pattern: str, handler, *, priority: int = 0,
                  filter_fn=None, min_severity: Severity | None = None) -> str
    async def start(self) -> None / async def close(self) -> None  # graceful drain

# parrot/core/events/bus/backends/base.py
class TransportBackend(Protocol):
    async def publish(self, envelope: EventEnvelope) -> None
    async def start_consumer(self, on_envelope) -> None
    async def close(self) -> None

# evb.py facade — EXISTING signatures preserved verbatim (see §6)
class EventBus:  # emit()/subscribe()/on()/publish()/unsubscribe() unchanged
    ...          # new kwargs (severity=..., min_severity=...) are additive-only
```

---

## 3. Module Breakdown

> Modules map 1:1 to the brainstorm capabilities, phased. Phase 1 alone delivers
> the user-visible goals (fire-and-forget, severity, alerts) with legacy API intact.

### Phase 1 — core fabric

### Module 1: `event-envelope`
- **Path**: `parrot/core/events/bus/envelope.py`, `bus/ingress_models.py`, `bus/converters.py`
- **Responsibility**: `Severity`, `EventEnvelope` (frozen, tz-aware enforcement), `IngressEnvelope` (Pydantic boundary model), converters from legacy `Event`, `LifecycleEvent` dict-form, and `HookEvent`.
- **Depends on**: nothing (foundation — blocks all other modules).

### Module 2: `event-bus-core`
- **Path**: `parrot/core/events/bus/core.py`
- **Responsibility**: per-priority queues, TaskGroup worker pool, glob/exact matching (reuse current algorithm), severity/filter predicates, per-handler timeout, retry-with-backoff, backpressure policies, meta-events (`bus.subscriber_error`, `bus.backpressure`) with recursion guard.
- **Depends on**: Module 1.

### Module 3: `event-bus-transports` (memory + protocol)
- **Path**: `parrot/core/events/bus/backends/base.py`, `backends/memory.py`, `backends/redis_pubsub.py`
- **Responsibility**: `TransportBackend` protocol; `MemoryBackend`; port of legacy Redis pub/sub as `RedisPubSubBackend` (kills the `start_redis_listener` duplicate-dispatch path).
- **Depends on**: Modules 1–2.

### Module 4: facade / legacy bridge
- **Path**: `parrot/core/events/evb.py` (rewrite internals, keep API)
- **Responsibility**: `EventBus` delegates to `BusCore`; `Event ↔ EventEnvelope` conversion; all four `events/__init__` exports preserved; `tests/core/events/test_eventbus_imports.py` must keep passing.
- **Depends on**: Modules 1–3.

### Module 5: `event-severity-alerting`
- **Path**: `parrot/core/events/bus/subscribers/notification.py`
- **Responsibility**: `NotificationSubscriber` — threshold + sliding-window rules, rate-limit/dedup defaults (§2), delivery via `NotificationMixin.send_notification()`; `[bus.alerts]` TOML config parsing (navconfig).
- **Depends on**: Modules 1–2; `parrot.notifications`.

### Module 6: DLQ persistence
- **Path**: `parrot/core/events/bus/dlq.py`
- **Responsibility**: `bus.dlq` terminal handling; asyncdb append-only persistence in **both** memory and Streams modes (*resolved in brainstorm*); replay helper.
- **Depends on**: Modules 1–2; asyncdb.

### Phase 2 — durable distributed mode

### Module 7: `RedisStreamsBackend`
- **Path**: `parrot/core/events/bus/backends/redis_streams.py`
- **Responsibility**: `XADD parrot:stream:<topic-class>`; `XREADGROUP` consumer loop (per-instance consumer name), explicit `XACK`, `XAUTOCLAIM` sweeper, `event_id` TTL-set dedup; retention policy (`MAXLEN`/`MINID`) decided here (*resolved in brainstorm: evaluate during implementation*).
- **Depends on**: Module 3 protocol; `redis.asyncio` (already present).

### Phase 3 — ingress/egress fleet

### Module 8: hook→bus routing
- **Path**: `parrot/core/hooks/manager.py` (extend)
- **Responsibility**: `route_to_bus` mode publishing `hooks.<type>.<event>` envelopes; orchestrator callback untouched; optional orchestrator flag to consume via subscription.
- **Depends on**: Module 4.

### Module 9: `event-ingress-adapters`
- **Path**: `parrot/core/events/bus/ingress/websocket.py`, `ingress/grpc.py`, proto under `parrot/core/events/bus/ingress/proto/`
- **Responsibility**: `WebSocketIngress` (aiohttp, `setup_routes`), `GrpcIngress` (`parrot.events.v1.PublishRequest`, A2UI-envelope-inspired shape); authentication; `IngressEnvelope` validation at boundary. New optional extra `parrot[grpc]`.
- **Depends on**: Modules 1, 4; `BaseHook` contract.

### Module 10: `event-audit-metrics`
- **Path**: `parrot/core/events/bus/subscribers/audit.py`, `subscribers/metrics.py`
- **Responsibility**: `AuditSubscriber` (asyncdb append-only), metrics subscriber (counters/latency histograms).
- **Depends on**: Modules 1–2; asyncdb.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_envelope_rejects_naive_timestamp` | 1 | naive `datetime` → `ValueError` |
| `test_envelope_frozen_and_slots` | 1 | immutability contract |
| `test_converters_lifecycle_hookevent_legacy` | 1 | three source shapes → identical envelope semantics |
| `test_publish_is_o1_enqueue` | 2 | `publish()` returns before any handler runs; slow handler does not delay emitter |
| `test_priority_queues_scheduling` | 2 | CRITICAL drains before LOW under load |
| `test_severity_filter_subscription` | 2 | `min_severity=WARNING` never receives INFO |
| `test_handler_error_isolation_model_b` | 2 | raising handler → `bus.subscriber_error` meta-event; siblings + emitter unaffected |
| `test_meta_event_recursion_guard` | 2 | error inside `bus.subscriber_error` handler does not loop |
| `test_backpressure_block_drop_reject` | 2 | three policies behave per config |
| `test_retry_backoff_then_dlq` | 2, 6 | exhausted retries land in persisted DLQ (asyncdb mock) |
| `test_facade_signatures_unchanged` | 4 | `emit/subscribe/on/publish/unsubscribe` accept legacy call shapes |
| `test_eventbus_imports` (existing) | 4 | all four exports still resolve — MUST NOT be modified |
| `test_notification_threshold_and_rate_rules` | 5 | severity threshold + N-errors-in-M-seconds window |
| `test_notification_dedup_and_storm_collapse` | 5 | 300 s dedup window; storm → single CRITICAL digest |
| `test_streams_ack_and_autoclaim` | 7 | unACKed message reclaimed; `event_id` dedup set honored (fakeredis or marked integration) |
| `test_hookmanager_route_to_bus` | 8 | hooks publish envelopes; legacy `set_event_bus` dual-emit still works |
| `test_ws_grpc_ingress_validation` | 9 | malformed external payload rejected at `IngressEnvelope` boundary |

### Integration Tests
| Test | Description |
|---|---|
| `test_end_to_end_memory_mode` | emit → workers → severity-filtered subscriber → notification rule fires (mocked async-notify) |
| `test_end_to_end_streams_mode` | two consumers in a group vs. real/fake Redis: at-least-once, no double-processing with dedup |
| `test_lifecycle_dual_emit_through_facade` | `EventRegistry.forward_to_bus` → envelope arrives; FEAT-177 fire-and-forget preserved |
| `test_graceful_shutdown_drain` | pending queue drained within deadline; no lost DLQ writes |

### Test Data / Fixtures
```python
@pytest.fixture
def bus_core():            # MemoryBackend, 2 workers, small queue for backpressure tests
    ...

@pytest.fixture
def frozen_envelope():     # valid tz-aware EventEnvelope factory
    ...

@pytest.fixture
def mock_notify(monkeypatch):  # patches NotificationMixin.send_notification
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/ -v`), including the **unmodified** existing `tests/core/events/test_eventbus_imports.py` and `tests/core/hooks/test_hookmanager_eventbus.py`.
- [ ] `EventBus.publish()`/`emit()` return without awaiting any handler (O(1) enqueue) — verified by test with a deliberately slow handler.
- [ ] Emitter-side overhead stays within the FEAT-177 budget (< 0.1% of LLM call latency); benchmark evidence saved to `artifacts/logs/`.
- [ ] `events/__init__` exports exactly `EventBus`, `Event`, `EventPriority`, `EventSubscription` (no removals).
- [ ] `EventRegistry.forward_to_bus` and `HookManager.set_event_bus` work with **zero changes** to their call sites.
- [ ] `Severity` is a distinct enum from `EventPriority`; subscriptions can filter by `min_severity`; severity never affects scheduling order.
- [ ] Error isolation model B: no handler exception ever propagates to the emitter; failures surface as `bus.subscriber_error` meta-events with recursion guard.
- [ ] `bus.dlq` events are persisted via asyncdb in BOTH memory and Streams modes.
- [ ] Streams mode delivers at-least-once across two consumer-group members with `event_id` dedup (integration test).
- [ ] `EventEnvelope` rejects naive datetimes; all internally-produced envelopes are tz-aware UTC.
- [ ] Notification defaults active out-of-the-box: 300 s dedup, 10/min channel throttle, storm collapse — all overridable via `[bus.alerts]`.
- [ ] Backpressure policy configurable per topic class (`block`/`drop_oldest`/`reject`) with `bus.backpressure` meta-event on activation.
- [ ] Graceful shutdown drains queues with deadline; no publishes accepted after `close()` begins.
- [ ] No new required runtime dependencies; gRPC ships as optional extra `parrot[grpc]`.
- [ ] Documentation updated in `docs/` (bus architecture, config reference for `[bus]` / `[[bus.alerts]]`, migration notes, "typed hot path vs app-wide fabric" doctrine).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Carried forward from the brainstorm Code Context and re-verified on `dev` 2026-07-16.

### Verified Imports
```python
# events/__init__.py re-exports EXACTLY four names (verified: events/__init__.py:13-20):
from parrot.core.events import EventBus, Event, EventPriority, EventSubscription
from parrot.core.events.evb import EventBus, Event, EventPriority   # canonical module
from parrot.core.events.lifecycle.base import LifecycleEvent
from parrot.core.events.lifecycle.registry import EventRegistry
from parrot.core.hooks.base import BaseHook, HookRegistry
from parrot.core.hooks.models import HookEvent, HookType, BrokerHookConfig  # models.py:9,31,202
from parrot.core.hooks.manager import HookManager
from parrot.notifications import NotificationMixin       # notifications/__init__.py:56
import redis.asyncio as aioredis                          # already used in evb.py
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/core/events/evb.py  (line numbers verified on dev 2026-07-16)
class EventPriority(Enum):                               # line 15
    LOW = 0; NORMAL = 5; HIGH = 10; CRITICAL = 15
@dataclass
class Event:                                             # line 24 — MUTABLE, naive datetime.now (line 29)
    event_type: str; payload: Dict[str, Any]
    event_id: str; timestamp: datetime; source: Optional[str]
    priority: EventPriority; correlation_id: Optional[str]; metadata: Dict[str, Any]
    def to_dict(self) -> Dict[str, Any]                  # line 35
    @classmethod
    def from_dict(cls, data) -> "Event"                  # line 48
@dataclass
class EventSubscription:                                 # line 62 — pattern, handler, subscriber_id, priority, filter_fn, async_handler
class EventBus:                                          # line 72
    CHANNEL_PREFIX = "parrot:events:"                    # line 83
    _event_history: List[Event]                          # line 101 — in-memory only
    async def close(self)                                # line 117 — punsubscribe fix landed (line 124)
    def subscribe(self, pattern, handler, *, priority=0, filter_fn=None) -> str  # line 129
    def unsubscribe(self, subscriber_id: str) -> bool    # line 171
    async def publish(self, event: Event) -> int         # line 188 — sequential awaits (the core defect)
    async def start_redis_listener(self)                 # line 257 — duplicated dispatch, to be absorbed by RedisPubSubBackend
    async def emit(self, event_type, payload, **kwargs) -> int  # line 294
    def on(self, pattern: str, **kwargs)                 # line 308 — decorator

# packages/ai-parrot/src/parrot/core/events/lifecycle/registry.py
class EventRegistry:                                     # line 90
    def subscribe(self, event_type, callback, *, where=None, forward_to_bus=False) -> str  # line 121
    async def emit(self, event: LifecycleEvent) -> None  # line 235 — never raises (model B)
    # dual-emit fire-and-forget: asyncio.create_task(self._event_bus.emit(...))  # line 283

# packages/ai-parrot/src/parrot/core/events/lifecycle/base.py
@dataclass(frozen=True)
class LifecycleEvent(ABC):                               # line 21
    trace_context: TraceContext; event_id: str
    timestamp: datetime                                  # timezone.utc — unlike evb.Event
    source_type: str; source_name: str
    def to_dict(self) -> dict[str, Any]                  # line 52 — strict json validation + "event_class" hint

# packages/ai-parrot/src/parrot/core/hooks/models.py
class HookEvent(BaseModel):                              # line 31
    hook_id: str; hook_type: HookType; event_type: str
    payload: Dict[str, Any]; metadata: Dict[str, Any]
    timestamp: datetime                                  # default_factory=datetime.now — naive
    target_type: Optional[str]; target_id: Optional[str]; task: Optional[str]

# packages/ai-parrot/src/parrot/core/hooks/manager.py
class HookManager:                                       # line 15
    def set_event_bus(self, bus: "EventBus") -> None     # line 43 — dual-emit "hooks.<type>.<event>"
    def register(self, hook: BaseHook) -> str            # line 111
    async def start_all(self) -> None                    # line 139
    async def stop_all(self) -> None                     # line 159

# packages/ai-parrot/src/parrot/core/hooks/base.py
class MessagingHook(Protocol):                           # line 17
class HookRegistry:                                      # line 39
class BaseHook(ABC):                                     # line 96
    @abstractmethod async def start(self) -> None        # line 169
    @abstractmethod async def stop(self) -> None         # line 173
    def setup_routes(self, app: Any) -> None             # line 176 — aiohttp route hook

# packages/ai-parrot/src/parrot/notifications/__init__.py — OUTBOUND delivery layer
class NotificationMixin:                                 # line 56
    async def send_notification(self, message, recipients, provider=NotificationProvider.EMAIL,
                                subject=None, report=None, template=None,
                                with_attachments=True, provider_options=None, **kwargs) -> Dict[str, Any]  # line 131
    # convenience: send_email / send_slack_message / send_telegram_message / send_teams_message

# packages/ai-parrot/src/parrot/outputs/a2ui/models.py — gRPC proto inspiration (resolved Q6)
class A2UIMessageBase(BaseModel):                        # line 157 — versioned-message envelope shape
```

### EventBus Instantiation & Injection Sites (verified 2026-07-16)

**Only ONE production instantiation** — everything else accepts an injected instance:

| Site | Kind | Location |
|---|---|---|
| `AutonomousOrchestrator` | **instantiates** `EventBus(...)` | `packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py:231` |
| `EventRegistry(event_bus=...)` | injection (dual-emit) | `lifecycle/registry.py:107` |
| `AbstractBot._init_events(event_bus=...)` | injection (via EventsMixin) | `parrot/bots/abstract.py:303,451`; `lifecycle/mixin.py:48-60` |
| `EvalRunner(event_bus=...)` | injection — emits `lifecycle.eval.*` | `parrot/eval/runner.py:144,504` |
| `HookManager.set_event_bus()` | injection (setter) | `parrot/core/hooks/manager.py:43` |
| `WebhookListener.set_event_bus()` | injection (setter) | `packages/ai-parrot-server/src/parrot/autonomous/webhooks.py:65` |
| `parrot.autonomous.evb` | pure re-export shim | `packages/ai-parrot-server/src/parrot/autonomous/evb.py:7` |

Tests instantiate directly in `tests/core/hooks/test_hookmanager_eventbus.py` and
`tests/unit/events/lifecycle/test_registry.py`. No Flowtask-side instantiation.

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `BusCore` | `EventBus` facade | delegation | `evb.py:72` (rewrite target) |
| `NotificationSubscriber` | `NotificationMixin.send_notification()` | method call | `notifications/__init__.py:131` |
| `WebSocketIngress`/`GrpcIngress` | `BaseHook.start/stop/setup_routes` | inheritance | `hooks/base.py:96,169,173,176` |
| `RedisStreamsBackend` consumer loop | `BaseBrokerHook._run_consumer` pattern | pattern reference | `hooks/brokers/base.py` |
| `HookManager.route_to_bus` | `EventBus.emit()` | method call | `hooks/manager.py:43` (existing dual-emit) |
| Envelope converters | `LifecycleEvent.to_dict()` | dict mapping | `lifecycle/base.py:52` |
| DLQ / `AuditSubscriber` | asyncdb | async driver | `pyproject.toml:71` (`asyncdb>=2.11.6`) |

### Does NOT Exist (Anti-Hallucination)
- ~~`Severity` enum anywhere in core/events~~ — does not exist yet; `EventPriority` is scheduling, not severity.
- ~~Any `asyncio.Queue`/worker pool in `EventBus`~~ — `publish()` awaits handlers inline, sequentially.
- ~~Redis Streams usage~~ — only `publish`/`psubscribe` pub/sub; no `XADD`/`XREADGROUP`/consumer groups anywhere.
- ~~DLQ, retry policy, dedup, ACK in evb.py~~ — none exist.
- ~~`NotificationSubscriber` / alerting rules~~ — nothing subscribes bus→notifications today.
- ~~Outbound send methods in `parrot/core/hooks/messaging.py`~~ — **inbound-only** webhook receivers (`_handle_telegram/_handle_whatsapp/_handle_teams`, base at line 21); despite the brainstorm's wording, it is NOT a notification delivery channel. Use `parrot.notifications.NotificationMixin` instead.
- ~~Slack or email hooks in `hooks/messaging.py`~~ — only Telegram (line 70), WhatsApp (line 121), MSTeams (line 186), all inbound.
- ~~gRPC or WebSocket ingress hooks~~ — hooks cover HTTP webhooks/IMAP/brokers/scheduler/watchdog only.
- ~~`EventBus` persistence of `_event_history`~~ — in-memory list only (evb.py:101), per-process, non-durable.
- ~~`HookManager.route_to_bus`~~ — proposed here; today only optional dual-emit via `set_event_bus`.
- ~~`parrot/core/events/bus/` package~~ — does not exist yet; created by this feature.
- ~~`close()`/`unsubscribe()` bug~~ — ALREADY FIXED on dev (evb.py:124 uses `punsubscribe()`); do not "re-fix".

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Frozen dataclass for the hot-path envelope** (FEAT-176 rationale: ~5x faster than Pydantic instantiation); Pydantic (`extra="forbid"`, `frozen=True`) ONLY at ingress boundaries — *resolved in brainstorm*.
- **Fire-and-forget dispatch**: follow `EventRegistry.emit`'s `asyncio.create_task` snippet (registry.py:283) and its contextvar recursion guard for meta-events.
- **Consumer lifecycle**: follow `BaseBrokerHook.start() → connect() + create_task(self._run_consumer())` (hooks/brokers/base.py).
- **Ingress adapters**: implement `BaseHook` (start/stop abstract, `setup_routes` for aiohttp) — hooks/base.py:96.
- **gRPC proto**: mirror the A2UI versioned-envelope shape (`A2UIMessageBase`, outputs/a2ui/models.py:157) for `parrot.events.v1.PublishRequest` — *resolved in brainstorm*.
- Async-first throughout; `self.logger` via `navconfig.logging`; Google-style docstrings + strict type hints; `uv` for any dependency changes.

### Known Risks / Gotchas
- **Queue full**: policy per topic-class — `block` (default, emits `bus.backpressure` warning meta-event), `drop_oldest`, or `reject` (raises to emitter; opt-in critical topics only).
- **Handler hangs**: per-handler `asyncio.timeout`; timeout counts as a failure toward retry/DLQ.
- **Redis down**: backend reconnect loop with backoff; in-memory dispatch continues (degraded-mode meta-event); publishes buffered up to a cap, then backpressure policy applies.
- **Duplicate delivery** (at-least-once): consumers must be idempotent in distributed mode — `event_id` TTL dedup set mitigates but does not eliminate; document loudly.
- **Alert storms**: mitigated by the three rate-limit defaults (§2); `NotificationSubscriber` failures must NOT recurse into `bus.dlq`→notify loops (severity of internal `bus.*` topics capped below alert threshold by default).
- **Shutdown**: graceful drain — stop accepting publishes, drain with deadline, `punsubscribe`/`XACK` outstanding, close connections.
- **Two subscription systems** (typed registry + topic bus) coexist by design — document "typed hot path vs app-wide fabric" doctrine to prevent future consolidation attempts.
- **Facade regression risk**: `test_eventbus_imports.py` and `test_hookmanager_eventbus.py` are the guard rails — they must pass unmodified.
- **Streams retention**: `MAXLEN` vs `MINID` and stream sharding decided during Module 7 implementation (*resolved in brainstorm: evaluate during implementation*) — record the decision in the task completion note.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `redis` (asyncio) | already present | Streams, consumer groups, dedup sets |
| `aiohttp` | already present | WebSocket ingress (server side) |
| `async-notify[all]` | `>=1.4.2` (already present, pyproject.toml:120) | NotificationSubscriber delivery |
| `asyncdb` | `>=2.11.6` (already present, pyproject.toml:71) | DLQ persistence + AuditSubscriber |
| `grpcio` / `grpcio-tools` | new, optional extra `parrot[grpc]` | gRPC ingress only |

---

## 8. Open Questions

> All brainstorm questions were resolved before this spec; echoed here for the audit trail.

- [x] Orchestrator callback path (`HookManager.set_event_callback`) deprecated in favor of bus subscription? — *Resolved in brainstorm*: **Keep it** (permanent low-latency direct path).
- [x] Envelope implementation: frozen dataclass vs Pydantic? — *Resolved in brainstorm*: **dataclass core + Pydantic model only at ingress boundaries** (accepted suggestion).
- [x] Redis Streams retention policy (`MAXLEN` vs `MINID`) and stream sharding? — *Resolved in brainstorm*: **evaluate during implementation** (Module 7; record decision in completion note).
- [x] Which app components instantiate `EventBus(...)`? — *Resolved by research*: only `AutonomousOrchestrator` (orchestrator.py:231); full table in §6.
- [x] Does `events/__init__.py` re-export names beyond `EventBus/Event/EventPriority`? — *Resolved by research*: yes, `EventSubscription` — facade must preserve all four.
- [x] gRPC ingress proto contract? — *Resolved in brainstorm*: **re-use A2UI envelope ideas** (`A2UIMessageBase` shape → `parrot.events.v1.PublishRequest`).
- [x] Notification rate-limiting/dedup defaults? — *Resolved in brainstorm*: user delegated; defaults specified in §2 (300 s dedup, 10/min throttle, storm collapse) — all configurable.
- [x] Should `bus.dlq` be persisted in in-memory mode? — *Resolved in brainstorm*: **yes, persisted** (asyncdb) in both modes.
- [x] Exact asyncdb driver/table naming convention for `bus.dlq` and audit tables (align with existing memory/audit tables if any) — *Owner: implementation (Module 6)*: use 'pg' in `navigator.evb_dlq` table

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — one worktree `feat-310-eventbus-v2`, tasks sequential in dependency order.
- **Internal parallelism (optional)**: after Module 1 (envelope) lands, Modules 2/5-prep and Phase 2/3 module pairs are parallelizable — but with a solo maintainer, sequential-in-one-worktree keeps `events/__init__.py` export merges trivial. `/sdd-task` should still mark `depends_on` precisely so parallel lanes remain possible.
- **Cross-feature dependencies**: none blocking. FEAT-212 (`LedgerRecorder`) subscribes to the lifecycle registry, which this feature does not touch. Verify no in-flight spec touches `parrot/core/events/lifecycle/*` or `AutonomousOrchestrator` before `/sdd-start`.
- **Merge order**: Phase 1 (Modules 1–6) can ship alone; Phases 2–3 may be follow-up task batches within this spec.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-16 | Jesus + Claude | Initial draft from eventbus-v2 brainstorm (Option B); messaging.py egress corrected to parrot.notifications |
