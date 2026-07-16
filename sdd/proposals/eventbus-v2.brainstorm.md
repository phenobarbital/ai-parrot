---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: Unified EventBus v2 — queue-based dispatch, severity, ingress channels, and notifications

**Date**: 2026-07-16
**Author**: Jesus (phenobarbital) + Claude
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

ai-parrot currently has **three parallel, weakly-integrated event subsystems**:

1. `parrot/core/events/evb.py` — a string-topic glob pub/sub `EventBus` (in-memory + optional Redis pub/sub).
2. `parrot/core/events/lifecycle/` (FEAT-176) — typed frozen `LifecycleEvent` dataclasses dispatched by `EventRegistry` (isinstance matching, error isolation model B, OTel/logging/webhook subscribers).
3. `parrot/core/hooks/` — external ingestion (Jira/GitHub webhooks, IMAP, Redis/RabbitMQ/MQTT/SQS brokers, scheduler, file watchers) whose events flow to an **orchestrator callback**, with the bus as an optional secondary dual-emit.

Consequences:

- **Three incompatible envelopes**: `Event` (mutable dataclass), `LifecycleEvent` (frozen dataclass + `TraceContext`), `HookEvent` (Pydantic BaseModel). No single closed contract for "an event in Parrot".
- **`EventBus.publish()` is NOT fire-and-forget**: handlers are `await`ed sequentially → head-of-line blocking; a slow handler stalls the emitter and all other subscribers. No internal queue, no worker pool, no backpressure. `EventPriority` only sorts the subscriber list; it does not influence scheduling.
- **Redis pub/sub is at-most-once and unpersisted**: crashed consumers lose events; no Redis Streams, consumer groups, ACKs, retries, DLQ, or durable replay (`_event_history` is a local Python list with O(n) slicing).
- **No severity model**: no DEBUG/INFO/WARNING/ERROR/CRITICAL on events, hence no severity-filtered subscriptions and **no alerting/notification pipeline** (despite `hooks/messaging.py` existing as an obvious outbound channel).
- **No gRPC / WebSocket ingress**, and existing HTTP ingress (hooks) does not feed the bus by default.
- **Duplicated dispatch logic**: `start_redis_listener()` re-implements `publish()`'s matching/dispatch inline (copy-paste divergence) and consumes messages sequentially inside the `async for`.
- Minor defects: `close()` calls `unsubscribe()` while the listener uses `psubscribe()` (must be `punsubscribe()`); naive `datetime.now()` in `Event` vs `timezone.utc` in `LifecycleEvent`; `event_id` exists but nothing deduplicates on it.

Affected: the autonomy/orchestrator layer, agent lifecycle observability, all hook-driven flows, and any future feature (alerting, audit, metrics) that needs a reliable in-app event fabric.

## Constraints & Requirements

- **Async-first**, Python 3.11+, `uv`-managed; deployable on GCP Cloud Run (ephemeral instances → durable state must live in the broker, not process memory).
- **Deterministic closed contracts**: single event envelope, frozen/immutable, `extra="forbid"` semantics, explicit serialization (aligned with existing SDD philosophy and FEAT-176's frozen-dataclass performance rationale — dataclasses are ~5x faster to instantiate than Pydantic on hot paths).
- **Non-breaking migration**: `EventRegistry.forward_to_bus`, `HookManager.set_event_bus`, and the `EventBus.emit/subscribe/on` public API must keep working (legacy bridge acceptable, hard break not).
- **Performance budget**: lifecycle dual-emit already commits to < 0.1% LLM-latency overhead (FEAT-177 TASK-1227); the new bus must not regress this — publish must be O(1) enqueue for the emitter.
- **At-least-once delivery** option for distributed mode (Redis Streams + consumer groups), with idempotency keys (`event_id`) for consumers; in-memory mode may remain at-most-once by config.
- **Severity is orthogonal to priority**: severity = log-level semantics (filtering/alerting); priority = dispatch scheduling.
- Error isolation model B (never interrupt the emitting flow) must be preserved everywhere.
- No heavyweight new runtime dependencies without justification; `redis.asyncio` already present; `aiohttp` already present for hooks.

---

## Options Explored

### Option A: Evolve `evb.py` in place (incremental hardening)

Keep the current `EventBus` class and API. Add: internal `asyncio.Queue` + worker pool so `publish()` becomes O(1) enqueue; `Severity` enum on `Event`; a `NotificationSubscriber`; switch Redis pub/sub → Redis Streams behind the same flag; fix known bugs (`punsubscribe`, tz-aware timestamps, `deque` history); deduplicate the listener dispatch path into `_dispatch()`.

✅ **Pros:**
- Smallest diff; no migration story needed.
- Fast to ship; fixes the worst runtime problems (blocking publish, lossy Redis).
- Low review surface for a solo maintainer.

❌ **Cons:**
- Does not unify the three envelopes — `Event` vs `LifecycleEvent` vs `HookEvent` fragmentation persists and keeps growing.
- Hooks still bypass the bus by default; gRPC/WS ingress remains ad-hoc.
- String-topic + typed-event duality stays unresolved (two subscription systems forever).
- Technical debt merely relocated, not paid.

📊 **Effort:** Low–Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `redis` (asyncio) | Streams + consumer groups | already a dependency |

🔗 **Existing Code to Reuse:**
- `parrot/core/events/evb.py` — everything, patched.
- `parrot/core/hooks/messaging.py` — outbound channel for notifications.

---

### Option B: Layered EventBus v2 — unified envelope, queue-core, pluggable transports, ingress/egress adapters

New package `parrot/core/events/bus/` with four layers and the existing subsystems refitted as adapters:

1. **Envelope** — single frozen dataclass `EventEnvelope` (topic, payload, `event_id`, tz-aware timestamp, `source`, `severity: Severity`, `priority`, `correlation_id`, optional `trace_context`, `metadata`). `LifecycleEvent.to_dict()` and `HookEvent` map into it via thin converters — one wire contract for the whole app.
2. **Core dispatcher** — in-process: `publish()` = O(1) enqueue into per-priority `asyncio.Queue`s drained by a bounded worker pool (`asyncio.TaskGroup`); explicit backpressure policy (block / drop-oldest / reject) per topic class; handler exceptions isolated (model B) and re-emitted as `bus.subscriber_error` meta-events; retry-with-backoff decorator + in-memory DLQ topic (`bus.dlq`).
3. **Transport backends (pluggable)** — `MemoryBackend` (default), `RedisStreamsBackend` (XADD/XREADGROUP + consumer groups + ACK + `XAUTOCLAIM` for stuck messages → at-least-once, durable, replayable), legacy `RedisPubSubBackend` kept for fan-out-only cases. Interface small enough that RabbitMQ/NATS backends are future drop-ins (the `hooks/brokers/*` code shows the shape).
4. **Ingress/egress adapters** —
   - *Ingress*: `HookManager` gains `route_to_bus=True` default-capable mode (hooks publish `hooks.<type>.<event>` envelopes instead of only invoking the orchestrator callback); new `WebSocketIngress` and `GrpcIngress` adapters implementing the existing `BaseHook` start/stop contract; existing webhook hooks unchanged.
   - *Egress*: `NotificationSubscriber` — subscribes with `severity >= threshold` (or rule: N errors in M seconds via sliding window) and delivers through `hooks/messaging.py` channels (Telegram/Slack/email); `AuditSubscriber` (append-only persistence via asyncdb); metrics subscriber (counters/latency) alongside the existing OTel lifecycle subscriber.

`EventBus` (evb.py) becomes a **facade** over the core with its current signature preserved; `EventRegistry.forward_to_bus` and `HookManager.set_event_bus` keep working untouched (they call `emit(channel, dict)` which the facade wraps into an envelope).

✅ **Pros:**
- One envelope, one dispatch core, one severity model → alerting, audit, metrics become "just subscribers".
- Emitter-side latency actually bounded (enqueue-only), honoring the FEAT-177 budget.
- Durable at-least-once distributed mode (Streams) without changing app code.
- Hooks/lifecycle investments preserved — they become ingress/typed-layer adapters, not rewrites.
- gRPC/WS ingress slots into the proven `BaseHook` lifecycle.

❌ **Cons:**
- Largest design surface; needs a real spec (ThemeConfig-v2-style SDD) and phased delivery.
- Backpressure/DLQ semantics add config knobs that must be documented.
- Two dispatch layers (typed EventRegistry + topic bus) still coexist — by design, but must be clearly documented as "typed hot path" vs "app-wide fabric".

📊 **Effort:** High (phaseable: Phase 1 core+envelope+facade, Phase 2 Streams backend, Phase 3 ingress/egress adapters)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `redis` (asyncio) | Streams, consumer groups | already present |
| `aiohttp` | WS ingress (server side) | already present via hooks |
| `grpcio` / `grpcio-tools` | gRPC ingress | optional extra `parrot[grpc]` |

🔗 **Existing Code to Reuse:**
- `parrot/core/events/lifecycle/registry.py` — error-isolation pattern, recursion guard, dual-emit fire-and-forget snippet (registry.py:280–300) as reference for safe `create_task` usage.
- `parrot/core/hooks/base.py` — `BaseHook` start/stop contract for new ingress adapters.
- `parrot/core/hooks/brokers/base.py` — consumer-task lifecycle pattern (`_run_consumer`).
- `parrot/core/hooks/messaging.py` — notification delivery channels.
- `parrot/core/events/lifecycle/subscribers/webhook.py` — outbound webhook egress pattern.

---

### Option C: Adopt an external event framework (FastStream / broadcaster / nats-py) as transport core

Replace the custom bus with FastStream (broker-agnostic pub/sub over Redis/RabbitMQ/NATS/Kafka) wrapped in a thin Parrot facade; keep lifecycle registry as-is.

✅ **Pros:**
- Broker abstraction, retries, serialization, testing utilities for free.
- Less custom dispatch code to maintain.

❌ **Cons:**
- Framework-shaped API (decorator-driven app object) conflicts with Parrot's explicit, deterministic contract philosophy and its existing lifecycle/hook architecture.
- FastStream's in-memory story is test-oriented; Parrot needs first-class in-process mode.
- New heavyweight dependency in the critical path of every deployment; version-coupling risk.
- Migration of hooks/lifecycle dual-emit is *more* work than Option B, not less.

📊 **Effort:** Medium (integration) + ongoing dependency risk

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `faststream` | broker abstraction | large surface; verify maturity |

🔗 **Existing Code to Reuse:**
- Minimal — most existing bus/hook plumbing would be replaced or wrapped.

---

## Recommendation

**Option B** is recommended because:

- The core problems are *architectural* (three envelopes, no queue core, ingress not routed to the bus) — Option A patches symptoms and leaves the fragmentation compounding with every new feature (A2UI, autonomy, trading swarm all emit events).
- Option B preserves the two best existing investments (typed lifecycle registry, hook ingestion fleet) by demoting/promoting them into well-defined layers instead of rewriting them.
- It is honestly more expensive up front, but it is phaseable, and Phase 1 alone (envelope + queue core + facade + severity + NotificationSubscriber) already delivers the user-visible goals (fire-and-forget, severity, alerts) with the legacy API intact.
- Option C trades custom code for a framework whose idioms fight the codebase's deterministic-contract philosophy and whose dependency weight is unjustified when `redis.asyncio` Streams covers the distributed requirement.

Trade-off accepted: typed `EventRegistry` and topic-based bus remain two subscription systems. This is intentional — typed events for the agent hot path (isinstance dispatch, zero serialization), topic envelopes for the app-wide fabric — and must be documented as such.

---

## Feature Description

### User-Facing Behavior

- Developers publish with `await bus.emit("order.created", payload, severity=Severity.INFO)` — the call returns in microseconds (enqueue only); handlers run on workers.
- `@bus.on("order.*", min_severity=Severity.WARNING)` subscribes with glob + severity filtering; `filter_fn` and `priority` keep working.
- `Notifier` config (TOML, navconfig-style) maps severity thresholds / error-rate rules to messaging channels: `[[bus.alerts]] min_severity="ERROR" channel="telegram" target="ops"`.
- Enabling `backend="redis-streams"` gives durable, replayable, consumer-group delivery across Cloud Run instances with zero app-code change.
- Hooks (Jira, GitHub, IMAP, brokers, scheduler) publish to `hooks.<type>.<event>` topics by default; the orchestrator callback becomes just another subscriber.
- New WS/gRPC ingress endpoints accept external envelopes (authenticated) and inject them into the bus.

### Internal Behavior

- `publish()` validates the envelope, appends to a bounded per-priority `asyncio.Queue`, returns. Worker tasks (TaskGroup, N configurable) pull, match subscriptions (exact dict + glob list, current algorithm reused), apply severity/filter predicates, invoke handlers with per-handler timeout, and route failures through retry policy → `bus.dlq` topic after exhaustion.
- Meta-events (`bus.subscriber_error`, `bus.dlq`, `bus.backpressure`) are themselves envelopes with a recursion guard (contextvar, same pattern as lifecycle registry).
- `RedisStreamsBackend`: `publish` → `XADD parrot:stream:<topic-class>`; consumer loop → `XREADGROUP` with per-instance consumer name, explicit `XACK` after handler success, `XAUTOCLAIM` sweeper for messages stuck past `min_idle_time`; `event_id` used as dedup key in a TTL'd Redis set for idempotency.
- Facade keeps `EventBus.emit/subscribe/on/publish` signatures; internally converts legacy `Event` ↔ `EventEnvelope`. `lifecycle` dual-emit and `HookManager.set_event_bus` need zero changes.

### Edge Cases & Error Handling

- **Queue full**: policy per topic-class — `block` (default, with warning meta-event), `drop_oldest`, or `reject` (raises to emitter; only for opt-in critical topics).
- **Handler raises**: caught, logged, `bus.subscriber_error` emitted (guarded), retry per policy, DLQ terminal.
- **Handler hangs**: per-handler `asyncio.timeout`; timeout counts as failure.
- **Redis down**: backend enters reconnect loop with backoff; in-memory dispatch continues (degraded mode meta-event emitted); publishes buffered up to a cap, then backpressure policy applies.
- **Duplicate delivery** (at-least-once): consumers use `event_id` dedup set; handlers documented as idempotent-required in distributed mode.
- **Shutdown**: graceful drain — stop accepting publishes, drain queues with deadline, `punsubscribe`/`XACK` outstanding, close connections (fixes current `close()` bug class by design).
- **Naive timestamps**: envelope constructor rejects naive datetimes (`extra="forbid"` spirit).

---

## Capabilities

### New Capabilities
- `event-envelope`: unified frozen event contract (topic, severity, trace, correlation) with converters from `LifecycleEvent`/`HookEvent`.
- `event-bus-core`: queue-based in-process dispatcher — O(1) publish, worker pool, backpressure, retries, DLQ, meta-events.
- `event-bus-transports`: pluggable backend interface + `MemoryBackend`, `RedisStreamsBackend` (consumer groups, ACK, dedup), legacy `RedisPubSubBackend`.
- `event-severity-alerting`: severity model + `NotificationSubscriber` with threshold/rate rules delivering via messaging channels.
- `event-ingress-adapters`: hook→bus default routing, `WebSocketIngress`, `GrpcIngress` (BaseHook contract).
- `event-audit-metrics`: `AuditSubscriber` (asyncdb append-only) and metrics subscriber.

### Modified Capabilities
- `lifecycle-events` (FEAT-176/177): dual-emit target becomes the facade; no behavior change, spec updated to reference `EventEnvelope` as the bus-side wire format.
- `hooks-system`: `HookManager` gains `route_to_bus` mode; orchestrator callback re-registered as bus subscriber.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/core/events/evb.py` | modifies (becomes facade) | public API preserved; internals delegated |
| `parrot/core/events/lifecycle/registry.py` | depends on | `forward_to_bus` path unchanged; typing of `emit(channel, dict)` intact |
| `parrot/core/hooks/manager.py` | extends | `route_to_bus` mode; `set_event_bus` semantics widened |
| `parrot/core/hooks/messaging.py` | depends on | delivery layer for NotificationSubscriber |
| `parrot/core/hooks/brokers/*` | unchanged (Phase 3: optional refit as ingress) | pattern reference for consumer loops |
| AutonomousOrchestrator | modifies | `_handle_hook_event` registered as subscriber instead of direct callback (behind flag) |
| navconfig / TOML | extends | `[bus]`, `[[bus.alerts]]` config sections |
| Deployment (Cloud Run) | depends on | Redis Streams requires Memorystore/Upstash reachable; consumer names per instance |

No breaking changes intended in Phase 1–2. New optional extra: `parrot[grpc]`.

---

## Code Context

### User-Provided Code

```python
# Source: packages/ai-parrot/src/parrot/core/events/evb.py (uploaded copy, local fix)
# close() must use punsubscribe() because the listener uses psubscribe():
await self._pubsub.punsubscribe()
await self._pubsub.close()
# NOTE: repo main still calls unsubscribe() here — bug to fix in Phase 1.
```

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/core/events/evb.py:72
class EventBus:
    CHANNEL_PREFIX = "parrot:events:"                    # line 83
    def subscribe(self, pattern, handler, *, priority=0, filter_fn=None) -> str  # line 126
    async def publish(self, event: Event) -> int         # line 185 — sequential awaits (the core defect)
    async def emit(self, event_type: str, payload: dict, **kwargs) -> int  # line 291
    def on(self, pattern: str, **kwargs)                 # line 305 — decorator

# From packages/ai-parrot/src/parrot/core/events/lifecycle/registry.py:90
class EventRegistry:
    def subscribe(self, event_type, callback, *, where=None, forward_to_bus=False) -> str  # line 121
    async def emit(self, event: LifecycleEvent) -> None  # line 235 — never raises (model B)
    # dual-emit via asyncio.create_task(self._event_bus.emit(channel, event.to_dict()))  # lines ~280-300

# From packages/ai-parrot/src/parrot/core/events/lifecycle/base.py:20
@dataclass(frozen=True)
class LifecycleEvent(ABC):
    trace_context: TraceContext
    event_id: str
    timestamp: datetime          # timezone.utc — unlike evb.Event (naive)
    source_type: str
    source_name: str
    def to_dict(self) -> dict[str, Any]   # strict json.dumps validation + "event_class" hint

# From packages/ai-parrot/src/parrot/core/hooks/models.py:31
class HookEvent(BaseModel):
    hook_id: str; hook_type: HookType; event_type: str
    payload: Dict[str, Any]; metadata: Dict[str, Any]
    timestamp: datetime          # default_factory=datetime.now — naive, inconsistent
    target_type: Optional[str]; target_id: Optional[str]; task: Optional[str]

# From packages/ai-parrot/src/parrot/core/hooks/manager.py:15
class HookManager:
    def set_event_bus(self, bus: "EventBus") -> None     # line 43 — dual-emit "hooks.<type>.<event>"
    def register(self, hook: BaseHook) -> str            # line 111
    async def start_all(self) -> None                    # line 139
    async def stop_all(self) -> None                     # line 159

# From packages/ai-parrot/src/parrot/core/hooks/base.py
class HookRegistry: ...          # satellite-package hook registration
class BaseHook(ABC):
    async def start(self) -> None; async def stop(self) -> None
    def setup_routes(self, app: Any) -> None             # aiohttp route hook for HTTP ingress

# From packages/ai-parrot/src/parrot/core/hooks/brokers/base.py
class BaseBrokerHook(BaseHook):
    # start() → connect() + asyncio.create_task(self._run_consumer())
    # _on_message() wraps payload into HookEvent "broker.message"
```

#### Verified Imports
```python
# events/__init__.py re-exports EXACTLY four names (verified 2026-07-16):
from parrot.core.events import EventBus, Event, EventPriority, EventSubscription
from parrot.core.events.evb import EventBus, Event, EventPriority   # canonical module
from parrot.core.events.lifecycle.base import LifecycleEvent
from parrot.core.events.lifecycle.registry import EventRegistry
from parrot.core.hooks.base import BaseHook, HookRegistry
from parrot.core.hooks.models import HookEvent, HookType, BrokerHookConfig  # models.py:9,31,202
from parrot.core.hooks.manager import HookManager
import redis.asyncio as aioredis                                     # already used in evb.py
```

#### Key Attributes & Constants
- `EventBus.CHANNEL_PREFIX` → `"parrot:events:"` (evb.py:83)
- `EventPriority.{LOW=0, NORMAL=5, HIGH=10, CRITICAL=15}` (evb.py) — dispatch priority, NOT severity
- `EventRegistry` bus channel format → `f"{bus_channel_prefix}.{EventClassName}"`, default prefix `"lifecycle"` (registry.py)
- `HookManager` bus channel format → `"hooks.<hook_type>.<event_type>"` (manager.py docstring)
- Lifecycle subscribers: `LoggingSubscriber` (subscribers/logging.py:21), `OpenTelemetrySubscriber` (subscribers/opentelemetry.py:39), `WebhookSubscriber` (subscribers/webhook.py:38)

#### EventBus Instantiation & Injection Sites (verified 2026-07-16)

**Only ONE production instantiation** — everything else accepts an injected instance:

| Site | Kind | Location |
|---|---|---|
| `AutonomousOrchestrator` | **instantiates** `EventBus(...)` | `packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py:231` |
| `EventRegistry(event_bus=...)` | injection (dual-emit) | `parrot/core/events/lifecycle/registry.py:107` |
| `AbstractBot._init_events(event_bus=...)` | injection (via EventsMixin) | `parrot/bots/abstract.py:303,451`; `lifecycle/mixin.py:48-60` |
| `EvalRunner(event_bus=...)` | injection — emits `lifecycle.eval.*` (TASK-1426) | `parrot/eval/runner.py:144,504` |
| `HookManager.set_event_bus()` | injection (setter) | `parrot/core/hooks/manager.py:43` |
| `WebhookListener.set_event_bus()` | injection (setter) | `packages/ai-parrot-server/src/parrot/autonomous/webhooks.py:65` |
| `parrot.autonomous.evb` | pure re-export shim | `packages/ai-parrot-server/src/parrot/autonomous/evb.py:7` |

No Flowtask-side instantiation found. Tests instantiate directly in
`tests/core/hooks/test_hookmanager_eventbus.py` and
`tests/unit/events/lifecycle/test_registry.py`.
**Facade consequence**: the singleton construction point for the v2 core is the
orchestrator; all injection sites work unchanged as long as `emit/subscribe/on/publish`
signatures are preserved. The facade must also keep exporting `EventSubscription`.

### Does NOT Exist (Anti-Hallucination)
- ~~`Severity` enum anywhere in core/events~~ — does not exist; `EventPriority` is scheduling, not severity.
- ~~Any `asyncio.Queue`/worker pool in `EventBus`~~ — `publish()` awaits handlers inline, sequentially.
- ~~Redis Streams usage~~ — only `publish`/`psubscribe` pub/sub; no `XADD`/`XREADGROUP`/consumer groups.
- ~~DLQ, retry policy, dedup, ACK~~ — none exist in evb.py.
- ~~`NotificationSubscriber` / alerting rules~~ — messaging channels exist in hooks, but nothing subscribes bus→notifications.
- ~~gRPC or WebSocket ingress hooks~~ — hooks cover HTTP webhooks/IMAP/brokers/scheduler/watchdog only.
- ~~`EventBus` persistence of `_event_history`~~ — in-memory list only, per-process, non-durable.
- ~~`HookManager.route_to_bus`~~ — proposed here; today only optional dual-emit via `set_event_bus`.

---

## Parallelism Assessment

- **Internal parallelism**: High. Phase 1 splits cleanly: (a) `EventEnvelope` + converters, (b) queue-core dispatcher, (c) facade/legacy bridge, (d) severity + NotificationSubscriber — (a) blocks the rest, (b)/(c)/(d) parallelizable in worktrees after (a) lands. Phase 2 (RedisStreamsBackend) is independent of Phase 3 (ingress adapters).
- **Cross-feature independence**: Touches `evb.py`, which lifecycle FEAT-176/177 imports (TYPE_CHECKING only) and `HookManager` references. Check in-flight specs touching `parrot/core/events/lifecycle/*` or the AutonomousOrchestrator before starting. A2UI/infographic work does not share files.
- **Recommended isolation**: per-spec (one spec per capability: `event-envelope`, `event-bus-core`, `event-bus-transports`, `event-severity-alerting`, `event-ingress-adapters`).
- **Rationale**: capabilities have narrow, explicit interfaces (envelope contract, backend protocol, BaseHook contract), so worktrees only contend on `events/__init__.py` exports.

---

## Open Questions

- [x] Should the orchestrator callback path (`HookManager.set_event_callback`) be deprecated in favor of bus subscription, or kept permanently as a low-latency direct path? — *Owner: Jesus*: Keep it
- [x] Envelope implementation: frozen `dataclass` (consistent with LifecycleEvent, faster) vs Pydantic v2 `frozen=True` (consistent with the rest of the stack, validation for ingress)? Suggestion: dataclass core + Pydantic model only at ingress boundaries. — *Owner: Jesus*: accepted suggestion
- [x] Redis Streams retention policy (`MAXLEN` vs `MINID`) and per-topic-class stream sharding — how many streams? — *Owner: Jesus*: evaluate during implementation.
- [x] Which app components currently instantiate `EventBus(...)`? — *Owner: Claude Code research*: **Answered** — exactly one production instantiation (`AutonomousOrchestrator`, orchestrator.py:231); all other references are injection points (EventRegistry, AbstractBot, EvalRunner, HookManager, WebhookListener). No Flowtask instantiation. Full table in Code Context → "EventBus Instantiation & Injection Sites".
- [x] Does `events/__init__.py` re-export names other than `EventBus/Event/EventPriority`? — *Owner: Claude Code research*: **Answered** — yes, one more: `EventSubscription`. `__all__ = ["EventBus", "Event", "EventPriority", "EventSubscription"]`. The facade must preserve all four exports (guarded by `tests/core/events/test_eventbus_imports.py`).
- [x] gRPC ingress: proto contract — reuse A2UI envelope ideas or define `parrot.events.v1.PublishRequest`? — *Owner: Jesus*: re-use A2UI envelope ideas
- [x] Notification rate-limiting/dedup window defaults (avoid alert storms on cascading failures). — *Owner: Jesus*: accept suggestions
- [x] Should `bus.dlq` be persisted (asyncdb table) in in-memory mode, or only in Streams mode? — *Owner: Jesus*: be persisted.
