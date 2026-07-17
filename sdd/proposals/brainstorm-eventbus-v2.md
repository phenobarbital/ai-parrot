---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: `navigator-eventbus` — standalone event fabric for ai-parrot, Flowtask, and navigator-auth

**Date**: 2026-07-16
**Author**: Jesus (phenobarbital) + Claude
**Status**: accepted
**Recommended Option**: B (layered bus) + standalone package extraction

> **Scope note**: this brainstorm covers the whole initiative and decomposes into
> **multiple specs across repositories** (see *Spec Decomposition*). Each spec gets
> its own SDD flow; this document is the shared architectural source.

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

## Packaging & Ecosystem Placement

**Decision: extract the bus core into a standalone package `navigator-eventbus`** (peer of `navigator` and `asyncdb`), consumed by ai-parrot, Flowtask, and navigator-auth.

### What lives where

| Layer | Package | Contents |
|---|---|---|
| **Core** | `navigator-eventbus` | `EventEnvelope` + `Severity`, queue-core dispatcher (workers, backpressure, retry, DLQ, meta-events), backend protocol + `MemoryBackend` + `RedisStreamsBackend` (+ legacy pub/sub), generic subscribers (logging, metrics), **`AbstractLedger[E]` protocol + `LedgerWriter` mixin + `HashChainMixin` + `PostgresLedgerBackend`/`InMemoryLedgerBackend` + ledger test utilities**, test utilities (`InMemoryBusFixture`, envelope factories) |
| **AI layer** | `ai-parrot` | lifecycle typed registry (unchanged), hooks as ingress adapters, `LifecycleEvent`/`HookEvent` → envelope converters, evb.py facade over the core, agent-specific topics (`agent.*`, `hooks.*`, `lifecycle.*`), **`SecurityAuditLedger` + `AgentEventLedger` + `BusAuditLedger` extending `AbstractLedger`** |
| **Task layer** | `flowtask` | task/DAG topics (`task.started`, `task.failed`, `flow.completed`), K8s dispatcher events, retry-orchestration subscribers |
| **AAA layer** | `navigator-auth` | `auth.*` topic contract (`auth.login.failed`, `auth.session.created`, `auth.policy.denied`, ...), `AuthAuditSubscriber`, **`AuthAuditLedger`** (extends `AbstractLedger` + `HashChainMixin` + KMS signing — see *Event Ledger base infrastructure* below), transactional outbox relay, notification rules for security alerts |

Dependency direction is strictly downward: apps → `navigator-eventbus`. The core knows nothing about agents, tasks, or auth. Cross-service communication (e.g. ai-parrot reacting to `auth.session.revoked`) happens only through the broker + the shared envelope contract — no code coupling.

### Event Ledger base infrastructure in navigator-eventbus

The codebase currently has **three independent, unrelated ledger implementations** with no shared base:

| Ledger | Location | Domain | Persistence | Extras |
|---|---|---|---|---|
| `AuditLedger` | `parrot.security.audit_ledger` | Credential invocation auditing (FEAT-260) | In-memory + optional async storage callable | KMS signing (`AbstractKMSSigner`: HMAC-SHA256 / Azure Key Vault), key fingerprinting |
| `EventLedger` | `parrot.autonomous.ledger` (ai-parrot-server) | Autonomous agent lifecycle (FEAT-212) | ABC → `PostgresLedgerBackend`, `InMemoryLedgerBackend` | Crash-resume via `find_incomplete()`, `LedgerRecorder` queue-based subscriber, batch flush |
| `AuditSubscriber` | `parrot.core.events.bus.subscribers.audit` | EventBus traffic audit trail (FEAT-310) | Postgres `navigator.evb_audit` table | Bounded queue, drop-oldest, topic pattern filtering |

All three enforce **append-only semantics**, persist to Postgres in production, and offer in-memory test alternatives — but share zero code. Each re-invents the same patterns: batched async writes, background flush tasks, sequence numbering, read projections.

**Decision: extract `AbstractLedger` protocol + shared infrastructure to `navigator-eventbus`.**

The base layer provides:

1. **`AbstractLedger[E]` protocol** — generic over the entry type `E` (a Pydantic `BaseModel`):
   - `async append(entry: E) -> int` — persist, return monotonic sequence number.
   - `async read(*, since_seq, limit, **filters) -> list[E]` — ordered replay.
   - `async count(**filters) -> int` — entry count with optional filtering.
   - Property `name: str` — ledger identity for logging/metrics.

2. **`LedgerWriter` mixin** — reusable non-blocking write path (the pattern repeated in `LedgerRecorder` and `AuditSubscriber`):
   - Bounded `asyncio.Queue` + configurable `batch_size` + background `_flush_loop` task.
   - Backpressure policy: `block` (default) / `drop_oldest`.
   - Graceful drain on `close()`.

3. **`HashChainMixin`** — optional append-only integrity guarantees:
   - Each entry stores `prev_hash` (SHA-256 of the previous entry's canonical bytes).
   - `async verify_chain(since_seq, until_seq) -> ChainVerificationResult` — validates an unbroken chain.
   - Composable with signing (the security domain adds KMS signing on top of the hash chain).

4. **Backend protocol** — `AbstractLedgerBackend[E]` for pluggable storage:
   - `PostgresLedgerBackend` (asyncdb) — generic, table name configurable.
   - `InMemoryLedgerBackend` — for tests.
   - Future: `SQLiteLedgerBackend` (local-first agents), `BigQueryLedgerBackend` (analytics).

5. **Test utilities** — `InMemoryLedger`, assertion helpers (`assert_ledger_contains`, `assert_chain_valid`), entry factories.

Domain packages then build on this base:

| Package | Ledger | Extends base with |
|---|---|---|
| `navigator-auth` | `AuthAuditLedger` | `AbstractKMSSigner` (Ed25519/HMAC), transactional-commit semantics, `credential_fingerprint` field, RFC 3161 TSA optional |
| `ai-parrot` | `SecurityAuditLedger` (current `AuditLedger`) | KMS signing via `AbstractKMSSigner`, credential invocation domain |
| `ai-parrot-server` | `AgentEventLedger` (current `EventLedger`) | `find_incomplete()` crash-resume, `LedgerRecorder` lifecycle subscriber, `AgentLedgerState` read projection |
| `ai-parrot` | `BusAuditLedger` (current `AuditSubscriber`) | `EventEnvelope`-typed, topic-pattern filtering, bus attachment |

### Audit Ledger ≠ bus (critical constraint)

The auth Audit Ledger is **not** a bus subscriber. A fire-and-forget (or even at-least-once) bus cannot be the source of truth for authn/authz records:

1. navigator-auth writes the ledger record **synchronously, in the same transaction** as the auth decision — append-only, hash-chained, Ed25519-signed (reuse the attestation-system design: RFC 3161 TSA optional for qualified timestamping).
2. After commit, the event is emitted to the bus via **transactional outbox pattern** (ledger row + outbox row in one transaction; a relay task publishes outbox → bus and marks published) — avoids the dual-write problem.
3. The bus handles **propagation and reaction only**: security alerts, dashboards, session invalidation fan-out. If the bus is down, the audit trail remains complete.

This constraint is **reinforced** by the `AbstractLedger` extraction: the base protocol is intentionally transport-agnostic. A ledger is a persistence primitive — it does not depend on the bus, even though it ships in the same package. The bus may *subscribe* to a ledger's post-commit events (via outbox relay), but the ledger never calls bus APIs.

### Spec Decomposition

Each item below is an independent SDD spec with its own repo, branch, and flow:

| # | Spec | Repo | Depends on | Summary |
|---|---|---|---|---|
| 1 | `eventbus-core` | `navigator-eventbus` (new) | — | Package scaffold (uv, pyproject), envelope, dispatcher, MemoryBackend, test utils. **Phase 1 of Option B, relocated.** |
| 1b | `eventbus-ledger` | `navigator-eventbus` | 1 | `AbstractLedger[E]` protocol, `LedgerWriter` mixin, `HashChainMixin`, `PostgresLedgerBackend`/`InMemoryLedgerBackend`, test utilities. Ships in same package as core — ledger is a persistence primitive, not a bus feature. |
| 2 | `eventbus-redis-streams` | `navigator-eventbus` | 1 | Streams backend: consumer groups, ACK, XAUTOCLAIM sweeper, `event_id` dedup, retention config |
| 3 | `parrot-eventbus-migration` | `ai-parrot` | 1, 1b | evb.py → facade over core; converters; deps update; lifecycle `forward_to_bus` + `HookManager.set_event_bus` regression-tested unchanged; migrate `AuditLedger` + `EventLedger` + `AuditSubscriber` to `AbstractLedger` base |
| 4 | `parrot-ingress-adapters` | `ai-parrot` | 3 | hooks `route_to_bus` mode, WS/gRPC ingress, NotificationSubscriber via messaging channels |
| 5 | `navauth-audit-ledger` | `navigator-auth` | 1b | Transactional `AuthAuditLedger` extending `AbstractLedger` + `HashChainMixin`: append-only hash chain, Ed25519 signing via `AbstractKMSSigner`, asyncdb schema. Depends on ledger base from `navigator-eventbus`, NOT on the bus itself. |
| 6 | `navauth-eventbus-integration` | `navigator-auth` | 1, 5 | Outbox relay ledger→bus, `auth.*` topic contract, AuthAuditSubscriber (read-side), security alert rules |
| 7 | `flowtask-eventbus-adoption` | `flowtask` | 1 (2 for distributed) | Task/DAG topics, K8s pod dispatcher events, subscriber-driven retries |

Topic-contract governance: `auth.*`, `task.*`, `agent.*` namespace ownership documented in `navigator-eventbus` (a `TOPICS.md` registry) so producers/consumers across repos share one vocabulary.

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

> Capabilities map to the specs in *Spec Decomposition*; each lives in its owning repo's `docs/sdd/specs/`.

### New Capabilities
- `eventbus-core` (**navigator-eventbus**, spec 1): envelope + severity contract, queue-based dispatcher — O(1) publish, worker pool, backpressure, retries, DLQ, meta-events, MemoryBackend, test utilities.
- `eventbus-redis-streams` (**navigator-eventbus**, spec 2): durable at-least-once backend — consumer groups, ACK, XAUTOCLAIM, dedup, retention.
- `eventbus-ledger` (**navigator-eventbus**, spec 1b): `AbstractLedger[E]` protocol, `LedgerWriter` non-blocking write mixin, `HashChainMixin` append-only integrity, `PostgresLedgerBackend`/`InMemoryLedgerBackend`, test helpers. Transport-agnostic persistence primitive — no bus dependency.
- `parrot-eventbus-migration` (**ai-parrot**, spec 3): evb.py facade, `LifecycleEvent`/`HookEvent` → envelope converters, dependency swap; migrate existing `AuditLedger`, `EventLedger`, and `AuditSubscriber` onto the `AbstractLedger` base.
- `parrot-ingress-adapters` (**ai-parrot**, spec 4): hook→bus default routing, `WebSocketIngress`, `GrpcIngress`, NotificationSubscriber over messaging channels.
- `navauth-audit-ledger` (**navigator-auth**, spec 5): transactional `AuthAuditLedger` extending `AbstractLedger` + `HashChainMixin` — append-only hash-chained, Ed25519-signed, asyncdb-persisted. Depends on ledger base from navigator-eventbus; independent of the bus itself.
- `navauth-eventbus-integration` (**navigator-auth**, spec 6): outbox relay, `auth.*` topic contract, security alerting.
- `flowtask-eventbus-adoption` (**flowtask**, spec 7): `task.*`/`flow.*` topics, dispatcher events, subscriber-driven retries.

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
| `navigator-eventbus` (new repo/package) | new | core extraction target; publishes to PyPI; owns `TOPICS.md` namespace registry + `AbstractLedger` base infrastructure |
| `parrot.security.audit_ledger` | modifies | `AuditLedger` refactored to extend `AbstractLedger` from navigator-eventbus; `AbstractKMSSigner` stays in ai-parrot (domain-specific) |
| `parrot.autonomous.ledger` (ai-parrot-server) | modifies | `EventLedger` ABC replaced by `AbstractLedger` base; `LedgerRecorder` reuses `LedgerWriter` mixin; `PostgresLedgerBackend` delegated to navigator-eventbus generic backend |
| `parrot.core.events.bus.subscribers.audit` | modifies | `AuditSubscriber` refactored to use `AbstractLedger` + `LedgerWriter` mixin instead of hand-rolled queue+flush |
| `navigator-auth` | extends | `AuthAuditLedger` (extends `AbstractLedger` + `HashChainMixin`, transactional, bus-independent) + outbox relay + `auth.*` producers |
| `flowtask` | extends | adopts core for `task.*`/`flow.*` topics; K8s dispatcher emits envelopes |
| `asyncdb` | depends on | ledger schema + outbox table persistence layer |

No breaking changes intended in specs 1–3. New optional extras: `parrot[grpc]`, `navigator-eventbus[redis]`.

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
from parrot.core.events.evb import EventBus, Event, EventPriority   # events/__init__.py re-exports; VERIFY exact __init__ names
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

- **Internal parallelism**: Very high — the decomposition is multi-repo by design. Dependency graph: spec 1 (`eventbus-core`) is the only hard blocker for bus specs; specs 2, 3, and 6 fan out from it. **Spec 1b (`eventbus-ledger`) depends on spec 1** (shared package scaffold + asyncdb dependency wiring) but can largely develop in parallel once the package structure is scaffolded. **Spec 5 (`navauth-audit-ledger`) now depends on 1b** (uses `AbstractLedger` base) but the dependency is lightweight — the protocol is small and stabilizes early. Specs 4 and 7 follow their repo's migration spec.
- **Cross-feature independence**: In ai-parrot, spec 3 touches `evb.py` (imported TYPE_CHECKING-only by lifecycle FEAT-176/177) and `HookManager` — check in-flight specs on `parrot/core/events/lifecycle/*` and the AutonomousOrchestrator. A2UI/infographic work shares no files. navigator-auth and flowtask specs are isolated in their own repos.
- **Recommended isolation**: per-spec, per-repo. Within `navigator-eventbus`, spec 1 sub-tasks (envelope / dispatcher / MemoryBackend / test-utils) can use worktrees after the envelope contract lands.
- **Rationale**: interfaces between specs are explicit contracts (envelope schema, backend protocol, `TOPICS.md` namespaces, outbox table schema), so cross-repo work only synchronizes on the published version of `navigator-eventbus`. Pin specs 3/6/7 to a tagged pre-release (e.g. `0.1.0rc`) rather than a git dependency.

---

## Open Questions

- [ ] Should the orchestrator callback path (`HookManager.set_event_callback`) be deprecated in favor of bus subscription, or kept permanently as a low-latency direct path? — *Owner: Jesus*
- [ ] Envelope implementation: frozen `dataclass` (consistent with LifecycleEvent, faster) vs Pydantic v2 `frozen=True` (consistent with the rest of the stack, validation for ingress)? Suggestion: dataclass core + Pydantic model only at ingress boundaries. — *Owner: Jesus*
- [ ] Redis Streams retention policy (`MAXLEN` vs `MINID`) and per-topic-class stream sharding — how many streams? — *Owner: Jesus*
- [ ] Which app components currently instantiate `EventBus(...)`? (Sparse checkout only covered core/events + core/hooks — Claude Code must grep the full repo, incl. autonomy/orchestrator and Flowtask integration points.) — *Owner: Claude Code research*
- [ ] Does `events/__init__.py` re-export names other than `EventBus/Event/EventPriority`? Verify before writing the facade. — *Owner: Claude Code research*
- [ ] gRPC ingress: proto contract — reuse A2UI envelope ideas or define `parrot.events.v1.PublishRequest`? — *Owner: Jesus*
- [ ] Notification rate-limiting/dedup window defaults (avoid alert storms on cascading failures). — *Owner: Jesus*
- [ ] Should `bus.dlq` be persisted (asyncdb table) in in-memory mode, or only in Streams mode? — *Owner: Jesus*
- [x] Should the bus core live inside ai-parrot or navigator-auth? — *Owner: Jesus*: Neither — extract to standalone `navigator-eventbus` package; apps depend downward on it; the Audit Ledger stays transactional inside navigator-auth with an outbox relay to the bus.
- [ ] `navigator-eventbus` repo layout: new standalone repo vs. new package inside an existing navigator monorepo? Affects CI and release cadence. — *Owner: Jesus*
- [ ] Minimum dependency set for `navigator-eventbus` core: can it be zero-dep (stdlib only) with `redis` as an extra? Does it use navconfig or accept plain config objects (navconfig would drag Parrot-ecosystem deps into a supposedly neutral package)? — *Owner: Jesus*
- [ ] Outbox relay in navigator-auth: dedicated asyncio task in-process vs. Flowtask job? (In-process is simpler; Flowtask survives process restarts on Cloud Run better.) — *Owner: Jesus*
- [ ] Ledger hash-chain anchoring cadence and TSA usage (every record vs. periodic checkpoint) — reuse the attestation-system decision matrix. — *Owner: Jesus*
- [x] `TOPICS.md` governance: is a markdown registry enough, or should topic contracts be code (enum/constants package importable by all repos)? — *Owner: Jesus*: markdown registry (`TOPICS.md`) nace con la fase 1 en navigator-eventbus; suficiente para la primera iteración. Cada app registra sus topics al adoptar el paquete.
- [ ] Envelope versioning strategy (`schema_version` field?) — needed once three repos serialize/deserialize across a broker with independent release cycles. — *Owner: Jesus*
- [ ] `AbstractLedger` generic type constraint: should `E` be bound to `pydantic.BaseModel` (validation at ingress) or `dataclass` (faster instantiation on hot paths like `LedgerRecorder`)? Suggestion: `BaseModel` bound — ledger entries are persistence objects, not hot-path dispatch. — *Owner: Jesus*
- [ ] `HashChainMixin` anchoring strategy: per-record chaining (every append computes `prev_hash`) vs periodic checkpoint anchoring (every N records)? Per-record is simpler but more expensive at high throughput. — *Owner: Jesus*
- [ ] Should `AbstractKMSSigner` move to navigator-eventbus (as part of the ledger base) or stay in ai-parrot/navigator-auth (domain-specific)? If multiple packages need signed ledgers, centralizing avoids duplication. — *Owner: Jesus*
- [x] `LedgerWriter` mixin: should it support pluggable serialization (JSON, msgpack, protobuf) for the flush path, or always use JSON? Relevant for high-throughput ledgers in Flowtask. — *Owner: Jesus*: JSON por defecto usando `JSONContent` (orjson); cloudpickle como serialización opcional. El flush path siempre serializa a JSON vía orjson como baseline.
