---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-server]
tags: [telemetry, observability, eventbus, tenancy, cost, chat-storage]
---

# Feature Specification: Parrot telemetry event fan-out (lifecycle events → EventBus)

**Feature ID**: FEAT-710
**Jira**: NVP-506 (epic NVP-502) — replaces the FEAT-775 draft of the closed PR #1747
**Date**: 2026-10-20
**Author**: Jesús Lara (with Claude)
**Status**: draft
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

The Navigator telemetry epic (NVP-502) needs AI cost, tokens and error rate per **tenant**, user and agent,
written to a BigQuery sink (`TelemetryEvent` + `BigQueryBatchSubscriber`, NVP-505, which lands in
`navigator-eventbus`). The closed PR #1747 proposed doing this with a `TelemetryBridge` *inside* ai-parrot.
That design would have added a fourth in-process subscriber to every LLM call, recomputed cost a fourth time,
run BigQuery I/O in the agent process, collided with the existing `parrot.observability.setup_telemetry`,
and introduced a TROC-specific `program_slug` concept into the framework.

ai-parrot already has everything needed for an out-of-process design:
- `navigator-eventbus` is a core dependency (`packages/ai-parrot/pyproject.toml:187`), and the lifecycle
  `EventRegistry` used by every bot *is* `navigator_eventbus.lifecycle.registry.EventRegistry`.
- The registry has per-subscription dual-emit (`forward_to_bus=True`) to an `EventBus` channel
  `"{prefix}.{EventClassName}"`, fire-and-forget (FEAT-176/177, extracted in FEAT-313/317, brokers FEAT-316).
- Tenancy already exists (FEAT-707): handlers resolve the tenant server-side via `resolve_request_tenant`
  and pass `ask(tenant=...)`.

What is missing:
- Nothing forwards the four usage events to a bus: the global registry has no `EventBus`, and no
  subscription with `forward_to_bus=True` exists for them.
- The events carry `user_id`/`session_id` but no `tenant` and no `cost_usd`. A ContextVar cannot cross the
  bus, and an external consumer has no pricing tables.
- The tenant ContextVar is skills-specific (`_skill_tenant`, `skills/tenancy.py:77`) and is bound only for
  `tenant_based` bots.
- AgentTalk (`handlers/agent.py`) neither resolves nor passes the tenant. Its two `save_turn` calls omit
  `metadata`, so per-turn usage is lost.

### Goals

- G1. Forward `AfterInvokeEvent`, `InvokeFailedEvent`, `AfterClientCallEvent` and `ClientCallFailedEvent` to an
  `EventBus`, behind a config flag (default off), so any consumer, in-process or not, can subscribe.
- G2. Make the four events self-describing: add `tenant: Optional[str]` to all four, `user_id`/`session_id`
  to `AfterInvokeEvent` and `InvokeFailedEvent` (today only `BeforeInvokeEvent` has them, and it is not forwarded), and `cost_usd: Optional[float]`
  to `AfterClientCallEvent`. Cost is computed **once**, at the origin, with the process-shared `CostCalculator`.
- G3. Use one generic `current_tenant` ContextVar, bound on every `ask()`/`ask_stream()`, that
  `skills/tenancy.py` reuses. There is no `program`/`program_slug` concept anywhere in ai-parrot.
- G5. **Cost is computed exactly once per LLM call.** Today each subscriber computes it independently
  from the same `AfterClientCallEvent`: `UsageRecordingSubscriber` (`recorders/subscriber.py:103-104`),
  `MetricsSubscriber` (`subscribers/metrics.py:243-244`) and the trace subscriber (`subscribers/trace.py:276-277`).
  After this feature, the origin computes it (`clients/base.py`) and all three subscribers read `event.cost_usd`.
- G4. AgentTalk resolves the tenant with the existing `resolve_request_tenant` (same as `chat.py:454-458`),
  passes it to `ask`/`ask_stream`, and persists `metadata={usage, cost_usd, tenant, agent}` in both `save_turn`
  calls.

### Non-Goals (explicitly out of scope)

- A `TelemetryBridge`, the `TelemetryEvent` model, the BigQuery sink, or `setup_telemetry(app)` inside
  ai-parrot. All of these live in the external consumer (NVP-505, navigator-eventbus or a worker).
- Mapping tenant → TROC program / `client_id`. That is the consumer's job, and ai-parrot never learns "program".
- The question-topic clustering job (FEAT-775 draft Module 4). It can be specced separately against ChatStorage.
- Changing the `UsageRecord` PII contract, the Prometheus label set or the OTel span attributes.
- Forwarding `BeforeInvokeEvent` (carries `question` text), `ClientStreamChunkEvent` or tool events.
- New tenant-resolution logic. `_get_user_session` is not touched, and no request/agent/session precedence
  chain is added.

---

## 2. Architectural Design

### Overview

```
bots/base.py ask()/ask_stream()  ── binds current_tenant (explicit tenant → ctx.kwargs["tenant"])
   │ emits AfterInvoke / InvokeFailed  (now with tenant)
clients/base.py _emit_after_call / _emit_failed_call
   │ emits AfterClientCall (tenant + cost_usd via shared CostCalculator) / ClientCallFailed (tenant)
   ▼
global EventRegistry ──▶ existing subscribers (UsageRecording, Metrics, Trace)   [unchanged]
   │  attach_bus(bus, serializer=redact_usage_event)          (navigator-eventbus FEAT-711)
   │  4 × subscribe(..., forward_to_bus=True)  — only when PARROT_EVENT_FANOUT_ENABLED
   ▼
EventBus(transport="streams", publish_only=True, outbox=<per-worker SQLite path>)
   │  outbox write-ahead → XADD → ack ; relay re-publishes after failure/restart   (at-least-once)
   ▼
Redis Streams consumer group ──▶ external consumer (NVP-505: TelemetryEvent + BigQuery) — NOT in ai-parrot
                                  dedups by envelope event_id

AgentTalk ── resolve_request_tenant ──▶ bot.ask(tenant=...) ; save_turn(metadata={usage,cost_usd,tenant,agent})
```

**Design decision: native `forward_to_bus` on top of navigator-eventbus FEAT-711.** Research found that the
registry forwarded `event.to_dict()` verbatim (leaking `error_message`), had no public way to attach a bus, and
that the only transport reachable from the `EventBus` facade (Redis pub/sub) is at-most-once while the producer
drops envelopes when the transport fails. Losing usage events is not acceptable, so these gaps are fixed
upstream in navigator-eventbus (`../navigator-eventbus/sdd/specs/durable-lifecycle-fanout.spec.md`, FEAT-711):
`EventRegistry.attach_bus()` + a payload serializer hook, `EventBus(transport="streams", publish_only=True,
outbox=...)`, and a persistent SQLite producer outbox with a relay. ai-parrot adds no forwarding class of its own.

**Tokens and cost are summed only from `AfterClientCallEvent`.** `AfterInvokeEvent.input/output_tokens` are an
aggregate of the same calls. The fan-out does not change them, but this spec documents the rule for consumers
(§7) so dashboards do not double count.

### Component Diagram
See Overview.

### Integration Points

| Piece | Location | Change |
|---|---|---|
| Invoke events | `core/events/lifecycle/events/invoke.py:34` `AfterInvokeEvent`, `:55` `InvokeFailedEvent` | + `tenant` |
| Client events | `core/events/lifecycle/events/client.py:45` `AfterClientCallEvent`, `:80` `ClientCallFailedEvent` | + `tenant`; + `cost_usd` (After only) |
| Event construction (client) | `clients/base.py:751` `AfterClientCallEvent(`, `:801` `ClientCallFailedEvent(` | fill `tenant=current_tenant.get()`, `cost_usd=` |
| Event construction (bot) | `bots/base.py:584/603/620`, `1757/1775/1794`, `2244/2260/2277` | fill `tenant=current_tenant.get()` |
| Dev-loop dispatcher events | `flows/dev_loop/dispatchers/claude.py:980`, `:1039` | none (fields default `None`) |
| ContextVars | `observability/context.py:63-73` | + `current_tenant` |
| Skill tenant | `skills/tenancy.py:77` `_skill_tenant` | becomes an alias of `current_tenant` |
| Tenant binding | `bots/base.py:1118-1120` (ask), `:1874-1876` (ask_stream) | bind `current_tenant` for every bot |
| Cost | `observability/cost/calculator.py:135` `CostCalculator`; `bootstrap.py:115` | shared process instance |
| Bootstrap | `observability/bootstrap.py:138` `add_provider` | `attach_bus` + 4 `forward_to_bus` subscriptions when flag on |
| AgentTalk | `handlers/agent.py:1883` `bot.ask(`, `:2653` `bot.ask_stream(`, `:2729`/`:2968` `save_turn(` | tenant + metadata |
| Tenant resolution | `handlers/scope.py:147` `resolve_request_tenant(app, request)`; pattern `handlers/chat.py:454-458` | reused as is |

### Data Models

```python
# core/events/lifecycle/events/invoke.py  — AfterInvokeEvent, InvokeFailedEvent
tenant: Optional[str] = None          # server-resolved tenant id (FEAT-707), never client-supplied
user_id: Optional[str] = None         # NEW on both invoke events (today only BeforeInvokeEvent has it)
session_id: Optional[str] = None      # NEW on both invoke events

# core/events/lifecycle/events/client.py
# AfterClientCallEvent
tenant: Optional[str] = None
cost_usd: Optional[float] = None      # None when no shared calculator or pricing unknown
# ClientCallFailedEvent
tenant: Optional[str] = None
```

Bus payload: produced by the serializer `redact_usage_event(event)` = `event.to_dict()` (includes `event_class`) minus the keys in `FORWARD_DENYLIST = {"error_message"}`; it returns `None` (skip) for any event class outside the four.

ChatStorage turn metadata (both AgentTalk call sites):
`{"usage": CompletionUsage.model_dump() | None, "cost_usd": float | None, "tenant": str | None, "agent": str}`.

### New Public Interfaces

```python
# observability/context.py
current_tenant: ContextVar[Optional[str]]            # "parrot_current_tenant", default None

# observability/cost/__init__.py (or calculator.py)
def get_shared_cost_calculator() -> Optional[CostCalculator]: ...
def set_shared_cost_calculator(calc: Optional[CostCalculator]) -> None: ...

# observability/fanout.py (new)
def redact_usage_event(event: LifecycleEvent) -> Optional[dict[str, Any]]: ...   # BusSerializer (FEAT-711)
def setup_event_fanout(bus: Optional[EventBus] = None) -> None: ...                # idempotent
async def shutdown_event_fanout() -> None: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible | Decided patterns / contracts |
|---|---|---|
| M1 tenant ContextVar | yes | token set/reset like `invocation_context`; `_skill_tenant` is the same object |
| M2 event fields | yes | dataclass fields with `None` defaults, appended last (frozen dataclasses, keyword construction) |
| M3 shared cost calculator | yes | module-level holder; bootstrap installs; clients read |
| M4 event fan-out wiring | yes | `attach_bus` + 4 `forward_to_bus=True` subscriptions + `redact_usage_event`; streams/publish-only/outbox bus; idempotent |
| M6 single cost computation | yes | subscribers read `event.cost_usd`; own calculator only as fallback when no shared calculator is installed |
| M7 chat hot-tier metadata | yes | `{**(metadata or {}), **fixed_keys}` at the Redis `ConversationTurn` |
| M5 AgentTalk tenant + metadata | yes | copy `chat.py:454-458`; metadata dict shape above |

### Module 1: generic `current_tenant`

Add `current_tenant` to `observability/context.py`. `skills/tenancy.py` stops owning a separate ContextVar:
`_skill_tenant = current_tenant`, and `current_skill_tenant`/`bind_skill_tenant`/`reset_skill_tenant` keep their
names and behavior. In `BaseBot.ask()` and `ask_stream()`, next to the existing `_enter_skill_tenant` call,
bind `current_tenant` for **every** bot (not only `tenant_based` ones) from `tenant` → `ctx.kwargs["tenant"]`, and
reset it in the matching `finally`. When the skill mixin is present and `tenant_based`, its own validated bind
still runs after this one and wins. Non-`tenant_based` skill bots still ignore the tenant for skill views,
because `_resolve_tenant` returns `None` for them (`skills/mixin.py:152-156`).

```python
# observability/context.py
current_tenant: ContextVar[Optional[str]] = ContextVar("parrot_current_tenant", default=None)
# verified: packages/ai-parrot/src/parrot/observability/context.py:73 (insert after current_memory_key_id)

# skills/tenancy.py
_skill_tenant = current_tenant   # verified: packages/ai-parrot/src/parrot/skills/tenancy.py:77
```

### Module 2: tenant and cost fields on the four events

Add the fields from §2 Data Models. Fill them at the construction sites: `clients/base.py:751/801` read
`current_tenant.get()` at construction time (same FEAT-228 rule as `agent_name`), and the nine `bots/base.py`
sites pass `tenant=current_tenant.get()`, `user_id=current_user_id.get()` and `session_id=current_session_id.get()`.
The origin also writes the computed cost into the response's `CompletionUsage.estimated_cost` (`models/basic.py:91`)
when that field is `None`, so AgentTalk can persist it without recomputing (design research S4). `cost_usd` is computed at `clients/base.py:751` with
`get_shared_cost_calculator()` (M3). When it returns `None`, or pricing is unknown, `cost_usd=None`. Computing
cost must never raise into the call path.

```python
# core/events/lifecycle/events/client.py — AfterClientCallEvent (after session_id, :76)
tenant: Optional[str] = None
cost_usd: Optional[float] = None
```

### Module 3: shared cost calculator

Add a process-level holder so the origin and the existing subscribers share one `CostCalculator`.
`bootstrap.py:115` installs the calculator it already builds, via `set_shared_cost_calculator(cost_calc)`, and
`shutdown_usage_recording()` clears it. The OTel path in `setup.py:245` installs its calculator the same way.
`UsageRecordingSubscriber` keeps receiving its calculator by injection, unchanged. When
`PARROT_EVENT_FANOUT_ENABLED` is true but local observability is off, the fan-out setup installs the shared
calculator itself (honoring `PARROT_PRICING_PATH`), so `cost_usd` is never absent because of local config (S3).

```python
def get_shared_cost_calculator() -> "Optional[CostCalculator]":
    """Return the process-wide CostCalculator installed by observability bootstrap, or None."""
def set_shared_cost_calculator(calc: "Optional[CostCalculator]") -> None:
    """Install (or clear with None) the process-wide CostCalculator."""
```

### Module 6: single cost computation (subscribers consume `event.cost_usd`)

`UsageRecordingSubscriber._on_client_after` (`recorders/subscriber.py:103`), `MetricsSubscriber`
(`subscribers/metrics.py:243`) and the trace subscriber (`subscribers/trace.py:276`) stop calling
`self._cost.cost_usd(...)` whenever the origin is authoritative. They use one shared helper:

```python
# observability/cost/__init__.py
def resolve_event_cost(event: "AfterClientCallEvent", fallback: "Optional[CostCalculator]") -> "Optional[float]":
    """Return the call's USD cost, computing it only when the origin did not.

    Returns ``event.cost_usd`` when it is not ``None`` (the origin already computed it). Only when it is
    ``None`` — emitters that bypass ``AbstractClient`` such as ``flows/dev_loop/dispatchers/claude.py:980``,
    or pricing unknown — compute with the shared calculator, else ``fallback``.
    """
```

The constructor `cost_calculator=` parameters stay (the fallback path and the existing tests use them).
The cumulative-cost logic in `UsageRecordingSubscriber` (`:111-114`) keeps working on the resolved value.
Result: one `cost_usd()` call per LLM call instead of up to three, and all sinks (Prometheus, OTel, usage
log, bus) report the identical number.

### Module 4: event fan-out wiring (native `forward_to_bus`, durable transport)

A new `observability/fanout.py`, used from `bootstrap.py` only when `PARROT_EVENT_FANOUT_ENABLED=true`. It
requires the navigator-eventbus release that contains FEAT-711; bump the pin in `packages/ai-parrot/pyproject.toml`.

1. Build the bus, unless one is injected (server/orchestrator):
   `EventBus(redis_url=PARROT_EVENT_FANOUT_REDIS_URL, transport="streams", publish_only=True,
   channel_prefix=PARROT_EVENT_FANOUT_CHANNEL_PREFIX or "parrot:events:",
   outbox=f"{PARROT_EVENT_FANOUT_OUTBOX_DIR}/{hostname}-{pid}.db")`.
   `publish_only` keeps parrot workers out of the consumer group, and the outbox gives at-least-once delivery
   across Redis outages and restarts.
2. `get_global_registry().attach_bus(bus, serializer=redact_usage_event)`.
3. Register a no-op callback with `forward_to_bus=True` for each of the four events, and keep the subscription ids.

```python
FORWARD_DENYLIST: frozenset[str] = frozenset({"error_message"})
FORWARDED_EVENTS: tuple[type[LifecycleEvent], ...] = (AfterInvokeEvent, InvokeFailedEvent,
                                                      AfterClientCallEvent, ClientCallFailedEvent)

def redact_usage_event(event: "LifecycleEvent") -> "Optional[dict[str, Any]]":
    """BusSerializer: to_dict() minus FORWARD_DENYLIST for FORWARDED_EVENTS; None for anything else."""

def setup_event_fanout(bus: "Optional[EventBus]" = None) -> None:
    """Attach the bus to the global registry and add the four forward_to_bus subscriptions. Idempotent."""

async def shutdown_event_fanout() -> None:
    """Unsubscribe, detach_bus(), close the bus (BusCore flushes the outbox relay once; leftovers stay on disk)."""
```

Setup is idempotent: a second call is a no-op. `shutdown_usage_recording()` calls `shutdown_event_fanout()`.
Bots must NOT also receive the same bus via `AbstractBot(event_bus=...)`, or every event is published twice (S2).
`stats()` of the bus (FEAT-711: `outbox_pending`, `outbox_rejected`, …) is exposed for health checks.

### Module 5: AgentTalk tenant and per-turn metadata

In `handlers/agent.py`, copy the `chat.py:454-458` pattern: pop and warn on a client-supplied `tenant`, set
`tenant = await resolve_request_tenant(app, self.request)`, and pass `tenant=tenant` to `bot.ask(` (:1883) and
`bot.ask_stream(` (:2653). In both `save_turn(` calls (:2729 streaming, `ai_message`; :2968 non-streaming,
`response`), pass
`metadata={"usage": msg.usage.model_dump() if msg.usage else None, "cost_usd": <sum of the turn's LLM-call costs or msg.usage.estimated_cost>, "tenant": tenant, "agent": agent_name}`.
`cost_usd` comes from `msg.usage.estimated_cost`, filled at the origin (M2). `_get_user_session` is not modified.
The background `save_turn` task receives the tenant explicitly in `metadata`, never by reading a ContextVar
that may already be reset (S6).

### Module 7: ChatStorage hot tier keeps caller metadata

`storage/chat.py` builds the Redis `ConversationTurn` with a fixed `metadata` dict (`output_mode`, `model`,
`provider`, `response_time_ms`) and drops the caller's `metadata`. Merge the caller metadata into it (fixed keys
win), so `usage`/`cost_usd`/`tenant`/`agent` survive hot-tier reads (S12).

---

## 4. Test Specification

### Unit Tests
- `test_current_tenant_bound_for_non_tenant_based_bot`: `ask(tenant="t1")` on a plain bot leaves
  `current_tenant == "t1"` inside the call and `None` after it.
- `test_skill_tenant_is_current_tenant`: `bind_skill_tenant("t")` is visible via `current_tenant.get()`.
- `test_skill_view_ignores_tenant_when_not_tenant_based`: a regression guard for FEAT-707.
- `test_after_client_call_carries_tenant_and_cost`: with a shared calculator and a priced model, `cost_usd`
  is set; without a calculator it is `None`, and a calculator that raises still gives `None` with no exception.
- `test_invoke_events_carry_tenant`.
- `test_fanout_channel_and_redaction`: a fake bus receives `lifecycle.ClientCallFailedEvent` without the
  `error_message` key and with `tenant`.
- `test_fanout_never_blocks_or_raises`: a slow or raising bus does not delay or break `registry.emit`
  (pattern: `tests/unit/events/lifecycle/test_registry_fire_and_forget.py`).
- `test_fanout_not_registered_when_flag_off`.
- `test_redact_usage_event_skips_other_events`.
- `test_fanout_bus_is_streams_publish_only_with_outbox`: the bus built from config uses those options.
- `test_cost_computed_once_per_call`: with a shared calculator spy and all three subscribers registered, one
  LLM call triggers exactly one `cost_usd()` call, and every sink sees the same value.
- `test_subscriber_fallback_without_shared_calculator`: with no shared calculator, an injected one is still used.
- `test_invoke_events_carry_user_and_session`.
- `test_dispatcher_events_still_priced`: an `AfterClientCallEvent` from the dev-loop dispatcher (no `cost_usd`)
  is still priced by the subscribers.
- `test_fanout_setup_idempotent`: two setups → four subscriptions, one publish per event.
- `test_nested_tenant_reset`: nested `ask()` calls restore the outer tenant.
- `test_chat_hot_tier_keeps_metadata`: the Redis `ConversationTurn.metadata` contains `usage` and `tenant`.
- `test_usage_record_unchanged`: `UsageRecord` still has no user, session or tenant fields.
- `test_agenttalk_ignores_client_tenant_and_passes_resolved`.
- `test_agenttalk_save_turn_metadata`: both call sites, with mocked ChatStorage.

### Integration Tests
| Test | Description |
|---|---|
| fan-out over a local EventBus | bot + mocked client call → a subscriber on the bus receives `AfterInvokeEvent` and `AfterClientCallEvent` dicts with the same `session_id` and `tenant` |

### Validation Contract
- `packages/ai-parrot/tests/unit/observability/test_client_global_bridge.py`
- `packages/ai-parrot/tests/unit/observability/test_usage_subscriber.py`
- `packages/ai-parrot/tests/unit/observability/test_bootstrap.py`
- `packages/ai-parrot/tests/unit/observability/test_metrics_subscriber.py`
- `packages/ai-parrot/tests/unit/observability/test_trace_subscriber.py`
- `packages/ai-parrot/tests/unit/observability/test_context.py`
- `packages/ai-parrot/tests/unit/events/lifecycle/test_registry_fire_and_forget.py`
- `packages/ai-parrot-server/tests/handlers/test_request_tenant_binding.py`
- `packages/ai-parrot/tests/test_chat_storage.py`

### Test Data / Fixtures
A fake `EventBus` with an async `emit(channel, payload)` that records calls; a `CostCalculator` built on the
bundled pricing.

---

## 5. Acceptance Criteria

- [ ] With `PARROT_EVENT_FANOUT_ENABLED=true`, the four events reach the bus on `"<prefix>.<EventClass>"`;
  with the flag off (default), no bus is attached and no subscription is added and behavior is identical to today.
- [ ] No forwarded payload contains `error_message`; none of the four events carries prompt or completion text.
- [ ] A slow, failing or unreachable bus never delays or fails `ask()`/`ask_stream()`.
- [ ] All four events carry `tenant`, server-resolved; a client-supplied tenant is ignored in AgentTalk and Chat.
- [ ] `AfterClientCallEvent.cost_usd` comes from the single shared `CostCalculator`; no new calculator is
  instantiated per call.
- [ ] `CostCalculator.cost_usd()` runs exactly once per LLM call (at the origin) when observability is booted;
  `UsageRecordingSubscriber`, `MetricsSubscriber` and the trace subscriber consume `event.cost_usd`.
- [ ] There is exactly one tenant ContextVar in the codebase; `program`/`program_slug` appears nowhere in ai-parrot.
- [ ] Delivery is at-least-once end to end: with Redis down or a worker restarted, no usage event is lost
  (the FEAT-711 outbox holds and relays it); parrot workers never join the consumer group (`publish_only`).
- [ ] FEAT-707 per-tenant skills behave as before (its tests pass unchanged).
- [ ] `AfterInvokeEvent` and `InvokeFailedEvent` carry `user_id` and `session_id`.
- [ ] Events not built by `AbstractClient` (dev-loop dispatcher) are still priced exactly as today.
- [ ] Fan-out setup is idempotent: one bus publish per event, never duplicated.
- [ ] Both AgentTalk `save_turn` calls persist `metadata.usage`, `metadata.cost_usd`, `metadata.tenant`, `metadata.agent`,
  in both the Redis hot tier and the cold tier.
- [ ] `UsageRecord`, the Prometheus labels and the OTel span attributes are unchanged.

---

## 6. Codebase Contract

Verified against `origin/dev` @ `fef06e5d7` (2026-10-20).

### Verified Imports
```python
from parrot.core.events.lifecycle import get_global_registry           # used at observability/bootstrap.py:134-138
from parrot.core.events.lifecycle.events import (AfterInvokeEvent, InvokeFailedEvent,
    AfterClientCallEvent, ClientCallFailedEvent)                       # core/events/lifecycle/yaml_loader.py:33-47
from navigator_eventbus.lifecycle.registry import EventRegistry        # tests/unit/events/lifecycle/test_registry_fire_and_forget.py:21
from parrot.observability.cost.calculator import CostCalculator        # observability/bootstrap.py:113
from parrot.observability.context import current_agent_name, current_user_id, current_session_id
# handlers: from .scope import resolve_request_tenant                  # handlers/chat.py:34
```
`EventBus` import: as used at `ai-parrot-server/src/parrot/autonomous/orchestrator.py:245` (re-verify the import line in that file).

### Existing Class Signatures
```python
# navigator_eventbus/lifecycle/registry.py (installed 0.2.x)
class EventRegistry:
    def __init__(self, ..., event_bus: "Optional[EventBus]" = None, bus_channel_prefix: str = "lifecycle", ...)  # :104-113
    def subscribe(self, event_type, callback, ..., forward_to_bus: bool = False) -> str                  # :121-127
    def add_provider(self, provider: Any) -> list[str]                                                    # :200
    async def emit(self, event: LifecycleEvent) -> None   # forwards event.to_dict() verbatim at :280-285
# navigator_eventbus/lifecycle/base.py:52  LifecycleEvent.to_dict() -> dict (adds "event_class")
# navigator_eventbus/lifecycle/global_registry.py  get_global_registry() -> EventRegistry(forward_to_global=False), no bus

# parrot/core/events/lifecycle/events/invoke.py
@dataclass(frozen=True) class AfterInvokeEvent:   agent_name, method, duration_ms, input_tokens, output_tokens  # :34-51
@dataclass(frozen=True) class InvokeFailedEvent:  agent_name, method, duration_ms, error_type, error_message    # :55-72
# parrot/core/events/lifecycle/events/client.py
@dataclass(frozen=True) class AfterClientCallEvent: client_name, model, duration_ms, input_tokens, output_tokens,
    finish_reason, agent_name, user_id, session_id                                                            # :45-76
@dataclass(frozen=True) class ClientCallFailedEvent: client_name, model, duration_ms, error_type, error_message,
    agent_name, user_id, session_id                                                                           # :80-99

# parrot/observability/context.py
def invocation_context(agent_name, user_id=None, session_id=None, memory_key_id=None) -> Iterator[None]       # :105
# parrot/observability/cost/calculator.py:135  class CostCalculator; cost_usd(*, provider, model, input_tokens, output_tokens, cached_input_tokens=0)
# parrot/skills/tenancy.py:77-94  _skill_tenant, current_skill_tenant(), bind_skill_tenant(t)->Token, reset_skill_tenant(tok)
# parrot/skills/mixin.py:135  _resolve_tenant(explicit=None, ctx=None) -> Optional[str]   (None when not tenant_based, :152)
# parrot/skills/mixin.py:195  _enter_skill_tenant(tenant, ctx) -> Optional[Token]
# parrot/storage/chat.py:106  async def save_turn(*, ..., metadata: Optional[Dict[str, Any]] = None) -> str     # metadata at :124
# ai-parrot-server handlers/scope.py:147  async def resolve_request_tenant(app, request) -> str | None
```

### Integration Points
See §2 table.

### Does NOT Exist (Anti-Hallucination)
- `current_tenant` / `current_program_slug` ContextVars (only `_skill_tenant` exists).
- Any public `EventRegistry.attach_bus()` / `set_event_bus()` method.
- A process-wide shared `CostCalculator` accessor, or any `resolve_event_cost` helper.
- `TelemetryBridge`, `TelemetryEvent`, `BigQueryBatchSubscriber` in ai-parrot (and none must be added).
- Any `tenant` handling in `handlers/agent.py` (AgentTalk) today.
- A `cost_usd` or `tenant` field on any lifecycle event today.

### Edit Sites (Blueprint Anchors)

| File | Anchor | Line | Count | Action |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/observability/context.py` | `current_memory_key_id: ContextVar` | 73 | 1 | modify |
| `packages/ai-parrot/src/parrot/skills/tenancy.py` | `_skill_tenant: ContextVar` | 77 | 1 | modify |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/invoke.py` | `output_tokens: Optional[int] = None` | 51 | 1 | modify |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/invoke.py` | `error_message: str = ""` | 72 | 1 | modify |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py` | `session_id: Optional[str] = None   # per-session correlation (spans only)` | 76 (After), 99 (Failed) | 3 — disambiguate by enclosing class | modify |
| `packages/ai-parrot/src/parrot/clients/base.py` | `event = AfterClientCallEvent(` / `event = ClientCallFailedEvent(` | 751 / 801 | 1 / 1 | modify |
| `packages/ai-parrot/src/parrot/bots/base.py` | `AfterInvokeEvent(` / `InvokeFailedEvent(` | 584,1757,2244 / 603,620,1775,1794,2260,2277 | 3 / 6 | modify |
| `packages/ai-parrot/src/parrot/bots/base.py` | `_tenant_token = _enter(tenant, ctx)` | 1120 (ask), 1876 (ask_stream) | 2 | modify |
| `packages/ai-parrot/src/parrot/observability/bootstrap.py` | `cost_calc = CostCalculator(override_path=config.pricing_override_path)` | 115 | 1 | modify |
| `packages/ai-parrot/src/parrot/observability/bootstrap.py` | `ids = get_global_registry().add_provider(subscriber)` | 138 | 1 | modify |
| `packages/ai-parrot/src/parrot/observability/setup.py` | `cost_calc = CostCalculator(override_path=override)` | 245 | 1 | modify |
| `packages/ai-parrot/src/parrot/observability/cost/__init__.py` | — | — | — | modify (holder + `resolve_event_cost`) |
| `packages/ai-parrot/src/parrot/observability/recorders/subscriber.py` | `cost_usd = self._cost.cost_usd(` | 104 | 1 | modify |
| `packages/ai-parrot/src/parrot/observability/subscribers/metrics.py` | `cost = self._cost.cost_usd(` | 244 | 1 | modify |
| `packages/ai-parrot/src/parrot/observability/subscribers/trace.py` | `cost = self._cost.cost_usd(` | 277 | 1 | modify |
| `packages/ai-parrot/src/parrot/observability/fanout.py` | — | — | — | create |
| `packages/ai-parrot/src/parrot/storage/chat.py` | `"response_time_ms": response_time_ms,` (inside the Redis `ConversationTurn(` metadata) | 197 | 1 | modify |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | `response: AIMessage = await bot.ask(` | 1883 | 1 | modify |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | `async for chunk in bot.ask_stream(` | 2653 | 1 | modify |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | `chat_storage.save_turn(` | 2729, 2968 | 2 — first is streaming (`ai_message`), second non-streaming (`response`) | modify |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Construction-time ContextVar capture (FEAT-228 comment at `clients/base.py:761-763`): read
  `current_tenant` when building the event, never inside a subscriber.
- Fire-and-forget bus publishing, like `registry.py:276-290`: `create_task`, log on scheduling failure,
  never `await` the bus in the call path.
- Server-resolved tenant only, never from the body (`chat.py:454-458`, `ui_surfaces.py:621`).
- Config via navconfig: `PARROT_EVENT_FANOUT_ENABLED` (default false), `PARROT_EVENT_FANOUT_REDIS_URL`,
  `PARROT_EVENT_FANOUT_CHANNEL_PREFIX` (default `parrot:events:`), `PARROT_EVENT_FANOUT_OUTBOX_DIR` (required when
  enabled; startup fails loudly if unset or not writable), and the registry-level channel prefix
  `lifecycle` (final Redis channel e.g. `parrot:events:lifecycle.AfterClientCallEvent`).

### Known Risks / Gotchas
- **Consumer double counting:** sum tokens and cost only from `AfterClientCallEvent`; `AfterInvokeEvent`
  tokens are aggregates. Document this in the consumer contract (NVP-505).
- **Global registry is ContextVar-backed** (`global_registry.py`). Call `setup_event_fanout()` from the same
  bootstrap path that already registers `UsageRecordingSubscriber` (`bootstrap.py:138`), which is proven to
  observe all requests.
- **`ensure_observability_bootstrapped` OTel path returns early** (`bootstrap.py` before :111). The shared
  calculator must also be installed from `setup.py:245`, or `cost_usd` stays `None` under `OBSERVABILITY_BACKEND=otel`.
- **Frozen dataclasses:** new fields must have defaults and go last; every positional construction would
  break (all known sites use keywords; re-check `flows/dev_loop/dispatchers/claude.py:980/1039`).
- **Tenant alias:** making `_skill_tenant` the same ContextVar means a non-`tenant_based` bot now has a bound
  value. The skill code must keep gating on `tenant_based` (covered by a regression test).
- **Delivery is at-least-once, not exactly-once** (FEAT-711 outbox + Redis Streams). The consumer MUST dedup by
  envelope `event_id`. Residual window: a worker killed in the single loop iteration between the lifecycle emit
  and the outbox append loses that event (FEAT-711 §7).
- **Outbox storage:** `PARROT_EVENT_FANOUT_OUTBOX_DIR` must be a persistent volume, with one file per worker
  (`{hostname}-{pid}.db`). An ephemeral container disk defeats restart recovery.
- **PII:** `user_id`/`session_id` already travel on these events (spans only). With fan-out they cross the
  process boundary. The consumer (NVP-505) owns retention and access control.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| navigator-eventbus | >= the release containing FEAT-711 (0.4.0) — pin bump | `attach_bus`, serializer hook, `transport="streams"`, `publish_only`, outbox |

---

## 8. Open Questions

- [x] Q1. Payload-serializer hook / `attach_bus()` upstream — *Resolved with the user (2026-10-20)*: implemented in
  navigator-eventbus FEAT-711; ai-parrot uses native `forward_to_bus=True` and no forwarder class.
- [ ] Q2. Should the server reuse the autonomous orchestrator's `EventBus` instance when both are active, or
  always build a dedicated forwarding bus? — *Owner: Jesús Lara*
- [x] Q3. Source of `metadata.cost_usd` per turn — *Resolved by design research S4*: the origin writes the cost
  into `CompletionUsage.estimated_cost`; AgentTalk copies it and never recomputes.
- [x] Q4. Durability — *Resolved with the user (2026-10-20)*: losing events is not acceptable; Redis Streams +
  persistent producer outbox (navigator-eventbus FEAT-711), at-least-once.
- [x] Program vs tenant — *Resolved with the user (2026-10-20)*: use the generic `tenant`; `program_slug` is
  TROC-specific and its mapping lives in the external consumer.
- [x] Where the BigQuery sink lives — *Resolved with the user (2026-10-20)*: outside ai-parrot (NVP-505).

---

## 9. Design Research Cross-Check

Model: gpt-5.6-luna (codex-cli 0.162.1) · Status: completed · Brief: §1 problem/goals + agreed scope + code paths only (no §2–§7 draft).
All 12 `affected_paths` passed containment and existence checks.

| # | Suggestion | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Explicit global EventBus config on the registry | CONFIRM (rev 0.3) | First rejected for lack of a public API; the API is now added upstream (FEAT-711 `attach_bus`) | §2, §3 M4 |
| S2 | One idempotent forwarding provider | CONFIRM | Duplicate publishes possible if bots also get the bus | §3 M4, §4, §5 |
| S3 | Cost independent of local observability setup | CONFIRM | Fan-out on + observability off left `cost_usd` empty | §3 M3 |
| S4 | How origin cost reaches AgentTalk | CONFIRM | Verified `CompletionUsage.estimated_cost` (`basic.py:91`); origin fills it | §3 M2, M5, §8 Q3 |
| S5 | One tenant ContextVar bound on every ask | CONFIRM | Already the design | §3 M1 |
| S6 | Resolve/strip AgentTalk tenant once; explicit metadata to background task | CONFIRM | Already the design; background-task note added | §3 M5 |
| S7 | `user_id`/`session_id` on invoke events | CONFIRM | Verified missing (`invoke.py:34-72`) | §2, §3 M2, §5 |
| S8 | Sanitize failed-event payloads | CONFIRM | Already the design (denylist) | §3 M4 |
| S9 | Non-AbstractClient emitters | CONFIRM | Verified `dispatchers/claude.py:980/1039`; `resolve_event_cost` recomputes only when `cost_usd is None` | §3 M6, §4, §5 |
| S10 | Don't promise durable accounting over pub/sub | CONFIRM | Verified at-most-once (`redis_pubsub.py:10`); the user required durability → Streams + outbox (FEAT-711) | §2, §3 M4, §5, §7, §8 Q4 |
| S11 | Cross-layer test matrix | CONFIRM | Tests added | §4 |
| S12 | Redis hot tier drops caller metadata | CONFIRM | Verified `chat.py` `ConversationTurn` metadata | §3 M7, §5 |

---

## Worktree Strategy

- Isolation: one feature worktree `feat-FEAT-710-parrot-telemetry-event-fanout`; the sdd-coder engine gives
  each task its own sub-worktree.
- Module graph: M2 → M1 (events read `current_tenant`); M2 → M3 (`cost_usd` uses
  `get_shared_cost_calculator`); M6 → M2 + M3 (reads `event.cost_usd`, checks the shared holder); M4 → M2 (forwards the new fields, tests assert `tenant`); M7 has no edge; M5 → M2 (reads `estimated_cost`) and M5 → M1 (tenant
  binding through `ask`). M1 and M3 have no edge and can run concurrently.
- Shared files: `bots/base.py` (M1 binding + M2 event sites), `observability/bootstrap.py` (M3 + M4) —
  serialize those tasks.
- Exclusive resources: none.
- Cross-feature dependencies: **navigator-eventbus FEAT-711** (`durable-lifecycle-fanout`) must be released
  first; M4 is blocked on it, while M1–M3 and M5–M7 are not. The external consumer (NVP-505) depends on this
  feature's channel and payload contract.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-20 | Jesús Lara / Claude | Initial draft, replacing the FEAT-775 draft of PR #1747 |
| 0.2 | 2026-10-20 | Jesús Lara / Claude | Codex design research folded in (S1–S12); M7 added; Q3 resolved; Q4 added |
| 0.3 | 2026-10-20 | Jesús Lara / Claude | Forwarder class dropped: native `forward_to_bus` + durable Streams/outbox via navigator-eventbus FEAT-711; Q1 and Q4 resolved |
