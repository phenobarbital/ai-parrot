---
type: feature
base_branch: dev
---

# Feature Specification: Lifecycle Events System

**Feature ID**: FEAT-176
**Date**: 2026-05-15
**Author**: Jesus Lara
**Status**: approved
**Target version**: TBD (next minor)

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot currently lacks a structured observability layer for agent execution. The existing mechanism — `AbstractBot._trigger_event()` / `add_event_listener()` — is:

- **String-based and untyped** (no IDE help, no static guarantees).
- **Used only for a single event** (`EVENT_STATUS_CHANGED`) despite being intended as a general system.
- **Ad-hoc dispatch** without ordering guarantees, error isolation, or distributed transport.
- **Disconnected from `EventBus`**: events emitted by the bot never reach the distributed pub/sub layer.
- **Incompatible with OpenTelemetry**: no `TraceContext` propagation, so traces cannot be stitched across agent → client → tool boundaries.

Meanwhile, three adjacent systems already exist in the repo and must NOT be confused with this feature:

1. **`parrot.core.hooks.*`** — *external* event sources (Jira webhooks, SharePoint, upload listeners) feeding the `AutonomousOrchestrator`. These are inbound triggers, not internal lifecycle interception.
2. **`parrot.core.events.evb.EventBus`** — distributed pub/sub transport (glob patterns, Redis-backed). This is the *transport*, not an event taxonomy.
3. **`AbstractToolkit._pre_execute` / `_post_execute`** — toolkit-scoped method hooks (used by `JiraToolkit` for OAuth credential resolution). Method-level, not event-level.

This feature introduces a **fourth concept**, deliberately separate from all three: *typed, read-only lifecycle observability events* covering agent / client / tool / message lifecycles, with W3C TraceContext propagation and integration into the existing `EventBus` as transport.

### Goals

- Provide a typed, asyncio-first observability event system covering `AbstractBot`, `AbstractClient`, and `AbstractTool` lifecycles.
- W3C Trace Context (`TraceContext`) propagation from day one — built for OpenTelemetry without retrofit.
- Per-agent `EventRegistry` plus opt-out global singleton for cross-agent observability.
- Dual-emit to the existing `EventBus` for distributed observability (Kubernetes / multi-worker).
- Configurable error isolation (subscriber failures emit a meta-event, never break the agent).
- YAML-declarative subscribers loadable by `BotManager` / `AgentRegistry`.
- Foundation for Phase 2 interceptors (not implemented here).
- Gradual deprecation path for the legacy `_trigger_event` / `add_event_listener` API.

### Non-Goals (explicitly out of scope)

- **Interceptors / behavior mutation** — events are strictly read-only (`@dataclass(frozen=True)`). Phase 2.
- **Crew / multi-agent events** — `BeforeCrewExecutionEvent`, `NodeHandoffEvent`, etc. Phase 1.5.
- **Sync callback support** — async-only; callers wrap sync code themselves.
- **Removal of `_trigger_event`** — kept with `DeprecationWarning`; removal is Phase 3.
- **Replacement of `EventBus`** — this feature *uses* `EventBus` as transport, does not modify it.
- **Replacement of `parrot.core.hooks.*`** — different concept, untouched.

---

## 2. Architectural Design

### Overview

The feature introduces a new submodule `parrot/core/events/lifecycle/` that defines:

1. A hierarchy of **typed, frozen dataclass events** (`LifecycleEvent` base + concrete subclasses).
2. A **`TraceContext`** dataclass implementing W3C Trace Context, propagated via the existing `permission_context` channel.
3. An **`EventRegistry`** that owns subscriptions for a given scope (per-agent, plus a process-wide global singleton).
4. An **`EventEmitterMixin`** added to `AbstractBot`, `AbstractClient`, and `AbstractTool` exposing a uniform `self.events` interface.
5. A set of **built-in subscribers** (`LoggingSubscriber`, `OpenTelemetrySubscriber`, `WebhookSubscriber`).
6. **YAML declarative loading** integrated with `BotManager` for agent definitions.
7. **Dual-emit** to `EventBus` with per-subscriber opt-in (mandatory opt-in for `ClientStreamChunkEvent`).
8. **Error isolation model (B)**: subscriber exceptions are caught, logged, and emit a `SubscriberErrorEvent` to the global registry; the agent flow continues.

### Component Diagram

```
                         ┌──────────────────────────────┐
                         │     global_registry          │
                         │   (singleton, opt-out)       │
                         │   + scope() context manager  │
                         └──────────────┬───────────────┘
                                        ▲
                                        │ forwards every event
                                        │ (unless agent opts out)
            ┌───────────────────────────┴────────────────────────────┐
            │                                                        │
   ┌────────┴────────┐                                      ┌────────┴────────┐
   │  Agent A        │                                      │  Agent B        │
   │  EventRegistry  │                                      │  EventRegistry  │
   │  (per instance) │                                      │  (per instance) │
   └────────┬────────┘                                      └────────┬────────┘
            │                                                        │
   emits via │ self.events.emit(evt)                                 │
            │                                                        │
   ┌────────┼────────────────────────────────────────────────────────┘
   │        ▼
   │   ┌─────────────────────────┐
   │   │ Local dispatch          │
   │   │ - filter by isinstance  │
   │   │ - call subscribers in   │
   │   │   registration order    │
   │   │ - reverse order for     │
   │   │   "After*" events       │
   │   │ - catch exc → meta-evt  │
   │   └────────────┬────────────┘
   │                │
   │                ▼ (opt-in per subscriber)
   │   ┌─────────────────────────┐
   │   │  EventBus.emit(         │
   │   │   "lifecycle.<Cls>",    │
   │   │   evt.to_dict())        │
   │   │  ── strict JSON-only ── │
   │   └─────────────────────────┘
   │
   └─→ (TraceContext propagated through permission_context to nested tools / sub-agents)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractBot` | extends | Adds `self.events: EventRegistry` and emits 6 events; deprecates `_trigger_event`. |
| `AbstractClient` | extends | Emits `BeforeClientCallEvent`, `AfterClientCallEvent`, `ClientCallFailedEvent`, `ClientStreamChunkEvent`. |
| `AbstractTool` | extends | Emits `BeforeToolCallEvent`, `AfterToolCallEvent`, `ToolCallFailedEvent` from `execute()`. |
| `AbstractToolkit` | unchanged | `_pre_execute` / `_post_execute` remain; future Phase 2 interceptors may bridge. |
| `EventBus` | uses | Dual-emit channel `lifecycle.<EventClassName>`. No changes to `EventBus` itself. |
| `BotManager` / `AgentRegistry` | extends | Loads `events:` block from YAML and wires subscribers to the agent's `EventRegistry`. |
| `permission_context` | extends | Adds `trace_context: TraceContext` field; propagated to tools and sub-agents. |
| `_trigger_event` (legacy) | replaces | Re-routed internally through the new emit pipeline; emits `DeprecationWarning`. |

### Data Models

```python
# parrot/core/events/lifecycle/trace.py

from dataclasses import dataclass, field
from typing import Optional

@dataclass(frozen=True)
class TraceContext:
    """W3C Trace Context (https://www.w3.org/TR/trace-context/).

    Used for OpenTelemetry-compatible distributed tracing across agent,
    client, tool, and sub-agent (A2A) boundaries.
    """
    trace_id: str                          # 32 hex chars (16 bytes)
    span_id: str                           # 16 hex chars (8 bytes)
    trace_flags: int = 0                   # bit 0 = sampled
    trace_state: str = ""                  # vendor extension list
    parent_span_id: Optional[str] = None   # for tree reconstruction

    @classmethod
    def new_root(cls) -> "TraceContext": ...

    def child(self) -> "TraceContext":
        """Return a new context with the same trace_id, fresh span_id,
        and parent_span_id set to this context's span_id."""
        ...

    @classmethod
    def from_traceparent_header(cls, header: str) -> "TraceContext": ...
    def to_traceparent_header(self) -> str: ...
    def to_dict(self) -> dict: ...

    @classmethod
    def from_dict(cls, data: dict) -> "TraceContext": ...
```

```python
# parrot/core/events/lifecycle/base.py

from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid

from .trace import TraceContext


@dataclass(frozen=True)
class LifecycleEvent(ABC):
    """Read-only base class for every lifecycle event.

    Subclasses MUST be ``@dataclass(frozen=True)``. Attempts to mutate
    will raise ``FrozenInstanceError``.

    All fields must be JSON-serializable (str, int, float, bool, None,
    list, dict). Non-serializable values (e.g., live database connections)
    must be excluded or referenced by ID.
    """
    trace_context: TraceContext
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_type: str = ""    # populated by emitter ("agent", "client", "tool")
    source_name: str = ""    # populated by emitter (agent name, client name, tool name)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict.

        Raises:
            TypeError: If any field is not JSON-serializable.
        """
        ...
```

```python
# parrot/core/events/lifecycle/events/agent.py — Agent lifecycle

@dataclass(frozen=True)
class AgentInitializedEvent(LifecycleEvent):
    agent_name: str = ""
    agent_class: str = ""

@dataclass(frozen=True)
class AgentConfiguredEvent(LifecycleEvent):
    agent_name: str = ""
    llm_provider: str = ""
    llm_model: str = ""
    has_vector_store: bool = False

@dataclass(frozen=True)
class ToolManagerReadyEvent(LifecycleEvent):
    agent_name: str = ""
    tool_count: int = 0
    tool_names: tuple[str, ...] = ()

@dataclass(frozen=True)
class AgentStatusChangedEvent(LifecycleEvent):
    agent_name: str = ""
    old_status: str = ""
    new_status: str = ""
```

```python
# parrot/core/events/lifecycle/events/invoke.py — Invocation lifecycle

@dataclass(frozen=True)
class BeforeInvokeEvent(LifecycleEvent):
    agent_name: str = ""
    method: str = ""                  # "ask" | "ask_stream" | "conversation"
    question: str = ""
    user_id: Optional[str] = None
    session_id: Optional[str] = None

@dataclass(frozen=True)
class AfterInvokeEvent(LifecycleEvent):
    agent_name: str = ""
    method: str = ""
    duration_ms: float = 0.0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None

@dataclass(frozen=True)
class InvokeFailedEvent(LifecycleEvent):
    agent_name: str = ""
    method: str = ""
    duration_ms: float = 0.0
    error_type: str = ""
    error_message: str = ""
```

```python
# parrot/core/events/lifecycle/events/client.py — LLM Client lifecycle

@dataclass(frozen=True)
class BeforeClientCallEvent(LifecycleEvent):
    client_name: str = ""            # "anthropic" | "google" | "openai" | ...
    model: str = ""
    temperature: Optional[float] = None
    system_prompt_hash: str = ""     # SHA-256, never the prompt itself
    has_tools: bool = False

@dataclass(frozen=True)
class AfterClientCallEvent(LifecycleEvent):
    client_name: str = ""
    model: str = ""
    duration_ms: float = 0.0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    finish_reason: Optional[str] = None

@dataclass(frozen=True)
class ClientCallFailedEvent(LifecycleEvent):
    client_name: str = ""
    model: str = ""
    duration_ms: float = 0.0
    error_type: str = ""
    error_message: str = ""

@dataclass(frozen=True)
class ClientStreamChunkEvent(LifecycleEvent):
    """High-frequency event. NEVER dual-emits to EventBus unless the
    subscriber explicitly opts in via ``forward_to_bus=True``.
    """
    client_name: str = ""
    model: str = ""
    chunk_index: int = 0
    chunk_size_bytes: int = 0
```

```python
# parrot/core/events/lifecycle/events/tool.py — Tool lifecycle

@dataclass(frozen=True)
class BeforeToolCallEvent(LifecycleEvent):
    tool_name: str = ""
    tool_class: str = ""
    args_summary: dict = field(default_factory=dict)  # truncated for safety

@dataclass(frozen=True)
class AfterToolCallEvent(LifecycleEvent):
    tool_name: str = ""
    duration_ms: float = 0.0
    result_status: str = ""           # "success" | "partial"
    result_size_bytes: int = 0

@dataclass(frozen=True)
class ToolCallFailedEvent(LifecycleEvent):
    tool_name: str = ""
    duration_ms: float = 0.0
    error_type: str = ""
    error_message: str = ""
```

```python
# parrot/core/events/lifecycle/events/message.py

@dataclass(frozen=True)
class MessageAddedEvent(LifecycleEvent):
    agent_name: str = ""
    role: str = ""                    # "user" | "assistant" | "tool" | "system"
    content_length: int = 0
    has_tool_calls: bool = False
```

```python
# parrot/core/events/lifecycle/meta.py — Meta-events (model B error isolation)

@dataclass(frozen=True)
class SubscriberErrorEvent(LifecycleEvent):
    """Emitted to the global registry when a subscriber raises an
    uncaught exception. Never re-routed back to a subscriber that
    is itself failing (no infinite loops).
    """
    failed_subscriber: str = ""
    original_event_class: str = ""
    error_type: str = ""
    error_message: str = ""
    traceback: str = ""
```

### New Public Interfaces

```python
# parrot/core/events/lifecycle/registry.py

from typing import TypeVar, Callable, Awaitable, Type
from .base import LifecycleEvent
from parrot.core.events.evb import EventBus

E = TypeVar("E", bound=LifecycleEvent)
AsyncSubscriber = Callable[[LifecycleEvent], Awaitable[None]]


class EventRegistry:
    """Per-scope registry of typed event subscribers.

    Dispatch rules:
    - Subscribers are matched by ``isinstance(event, event_type)``.
    - Subclass subscriptions receive parent-class events:
      subscribing to ``LifecycleEvent`` receives everything;
      subscribing to ``BeforeToolCallEvent`` receives only that.
    - "After*" / "*Failed" events use REVERSE registration order
      for cleanup symmetry (last registered runs first).
    - Subscriber exceptions are caught, logged, and emit a
      ``SubscriberErrorEvent`` to the global registry.
    - Dual-emit to ``EventBus`` is per-subscriber opt-in.
    """

    def __init__(
        self,
        *,
        event_bus: Optional[EventBus] = None,
        bus_channel_prefix: str = "lifecycle",
        forward_to_global: bool = True,
    ) -> None: ...

    def subscribe(
        self,
        event_type: Type[E],
        callback: AsyncSubscriber,
        *,
        where: Optional[Callable[[E], bool]] = None,
        forward_to_bus: bool = False,
    ) -> str:
        """Register a subscriber. Returns a subscription_id for unsubscribe."""
        ...

    def unsubscribe(self, subscription_id: str) -> bool: ...

    def add_provider(self, provider: "EventProvider") -> list[str]:
        """Bulk-register all callbacks declared by an EventProvider."""
        ...

    async def emit(self, event: LifecycleEvent) -> None:
        """Dispatch the event to local subscribers and (opt-in) the bus.

        Never raises — subscriber exceptions are isolated per model (B).
        """
        ...
```

```python
# parrot/core/events/lifecycle/global_registry.py

def get_global_registry() -> EventRegistry:
    """Return the process-wide singleton EventRegistry."""
    ...

@contextmanager
def scope() -> Iterator[EventRegistry]:
    """Replace the global registry with a fresh one for the duration of
    the block. Restores the previous registry on exit. Required for test
    isolation.
    """
    ...
```

```python
# parrot/core/events/lifecycle/provider.py

from typing import Protocol, runtime_checkable

@runtime_checkable
class EventProvider(Protocol):
    """Bundles multiple callbacks for batch registration.

    Example:
        class TelemetryProvider:
            def register(self, registry: EventRegistry) -> None:
                registry.subscribe(BeforeInvokeEvent, self.on_invoke_start)
                registry.subscribe(AfterInvokeEvent, self.on_invoke_end)
                registry.subscribe(InvokeFailedEvent, self.on_invoke_fail)

            async def on_invoke_start(self, e: BeforeInvokeEvent) -> None: ...
            async def on_invoke_end(self, e: AfterInvokeEvent) -> None: ...
            async def on_invoke_fail(self, e: InvokeFailedEvent) -> None: ...
    """
    def register(self, registry: EventRegistry) -> None: ...
```

```python
# parrot/core/events/lifecycle/mixin.py

class EventEmitterMixin:
    """Mixin attached to AbstractBot, AbstractClient, AbstractTool.

    Provides a uniform ``self.events`` interface and lazy registry
    creation. Forwards every emit to the global registry unless
    disabled via ``forward_to_global=False`` at construction.
    """
    def _init_events(
        self,
        *,
        event_bus: Optional[EventBus] = None,
        forward_to_global: bool = True,
    ) -> None: ...

    @property
    def events(self) -> EventRegistry: ...
```

```python
# parrot/core/events/lifecycle/subscribers/

class LoggingSubscriber:
    """Logs every event via navconfig.logging at configurable level."""

class OpenTelemetrySubscriber:
    """Maps LifecycleEvents to OpenTelemetry spans.

    Optional dependency — requires ``opentelemetry-api`` and
    ``opentelemetry-sdk`` (declared in extras_require['otel']).
    """

class WebhookSubscriber:
    """POSTs serialized events to a configured HTTPS endpoint
    asynchronously. Includes HMAC signing if a secret is configured.
    """
```

### YAML Declarative Syntax

```yaml
# Example agent definition with events block
name: jira_specialist
llm: anthropic:claude-sonnet-4
prompt: |
  You are a Jira specialist.

events:
  # Optional: disable global forwarding for this agent (default: true)
  forward_to_global: true

  # Optional: bind to a specific EventBus instance (default: none)
  event_bus: ${EVENT_BUS_REF}        # navconfig reference

  subscribers:
    # Form 1: single callback + event filter
    - handler: parrot_tools.observability:log_tool_calls
      events: [BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent]
      where:
        tool_name: [jira_create_issue, jira_update_issue]
      forward_to_bus: false

    # Form 2: EventProvider — bundles multiple callbacks
    - provider: parrot.core.events.lifecycle.subscribers:OpenTelemetrySubscriber
      config:
        service_name: jira_specialist
        endpoint: ${OTEL_EXPORTER_OTLP_ENDPOINT}

    # Form 3: built-in subscriber
    - provider: parrot.core.events.lifecycle.subscribers:WebhookSubscriber
      events: [AfterInvokeEvent, InvokeFailedEvent]
      config:
        url: ${EVENTS_WEBHOOK_URL}
        secret: ${EVENTS_WEBHOOK_SECRET}
        forward_to_bus: true
```

---

## 3. Module Breakdown

### Module 1: TraceContext
- **Path**: `packages/ai-parrot/src/parrot/core/events/lifecycle/trace.py`
- **Responsibility**: W3C Trace Context dataclass with `new_root`, `child`, `to/from_traceparent_header`, `to/from_dict`.
- **Depends on**: stdlib only.

### Module 2: LifecycleEvent Base
- **Path**: `packages/ai-parrot/src/parrot/core/events/lifecycle/base.py`
- **Responsibility**: Frozen dataclass base with `trace_context`, `event_id`, `timestamp`, `source_type`, `source_name`, `to_dict()` with strict JSON validation.
- **Depends on**: Module 1.

### Module 3: Concrete Event Classes
- **Path**: `packages/ai-parrot/src/parrot/core/events/lifecycle/events/{agent,invoke,client,tool,message}.py`
- **Responsibility**: All 15 concrete event classes from §2 Data Models.
- **Depends on**: Module 2.

### Module 4: Meta-events
- **Path**: `packages/ai-parrot/src/parrot/core/events/lifecycle/meta.py`
- **Responsibility**: `SubscriberErrorEvent` for error isolation model (B).
- **Depends on**: Module 2.

### Module 5: EventRegistry
- **Path**: `packages/ai-parrot/src/parrot/core/events/lifecycle/registry.py`
- **Responsibility**: Per-scope dispatch, isinstance-based matching, reverse ordering for After/Failed events, error isolation, optional dual-emit to `EventBus`, optional forwarding to global registry.
- **Depends on**: Modules 2, 3, 4, existing `parrot.core.events.evb.EventBus`.

### Module 6: Global Registry & Scope
- **Path**: `packages/ai-parrot/src/parrot/core/events/lifecycle/global_registry.py`
- **Responsibility**: `get_global_registry()` singleton + `scope()` context manager for test isolation. Uses `contextvars.ContextVar` for thread/task safety.
- **Depends on**: Module 5.

### Module 7: EventProvider Protocol
- **Path**: `packages/ai-parrot/src/parrot/core/events/lifecycle/provider.py`
- **Responsibility**: Runtime-checkable Protocol for bundling related subscribers.
- **Depends on**: Module 5.

### Module 8: EventEmitterMixin
- **Path**: `packages/ai-parrot/src/parrot/core/events/lifecycle/mixin.py`
- **Responsibility**: Uniform `self.events` interface, lazy registry creation, global forwarding wiring.
- **Depends on**: Module 5, 6.

### Module 9: Built-in Subscribers — Logging
- **Path**: `packages/ai-parrot/src/parrot/core/events/lifecycle/subscribers/logging.py`
- **Responsibility**: `LoggingSubscriber` — logs every event via `navconfig.logging`. No external deps.
- **Depends on**: Module 3.

### Module 10: Built-in Subscribers — OpenTelemetry
- **Path**: `packages/ai-parrot/src/parrot/core/events/lifecycle/subscribers/opentelemetry.py`
- **Responsibility**: Maps lifecycle events to OTel spans. Lazy import of `opentelemetry.*`. Declared in `extras_require['otel']`.
- **Depends on**: Module 3, `opentelemetry-api>=1.25`, `opentelemetry-sdk>=1.25`.

### Module 11: Built-in Subscribers — Webhook
- **Path**: `packages/ai-parrot/src/parrot/core/events/lifecycle/subscribers/webhook.py`
- **Responsibility**: HTTPS POST of serialized events with optional HMAC-SHA256 signature. Reuses `aiohttp.ClientSession`.
- **Depends on**: Module 3, `aiohttp` (already a project dep).

### Module 12: AbstractBot Integration
- **Path**: `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFIED)
- **Responsibility**:
  - Mix in `EventEmitterMixin`.
  - Emit `AgentInitializedEvent` end of `__init__`.
  - Emit `AgentConfiguredEvent` end of `configure()`.
  - Emit `ToolManagerReadyEvent` after `ToolManager` population.
  - Emit `AgentStatusChangedEvent` from the `status` setter.
  - Emit `BeforeInvokeEvent` / `AfterInvokeEvent` / `InvokeFailedEvent` around `ask` / `ask_stream` / `conversation`.
  - Emit `MessageAddedEvent` when a message enters the conversation history.
  - Reroute existing `_trigger_event` calls through the new pipeline.
  - Emit `DeprecationWarning` from `add_event_listener`.
  - Add optional `trace_context: TraceContext | None = None` parameter to `ask` / `ask_stream` / `conversation` public methods.
- **Depends on**: Module 8.

### Module 13: AbstractClient Integration
- **Path**: `packages/ai-parrot/src/parrot/clients/base.py` (MODIFIED)
- **Class**: `AbstractClient` (defined at line 233).
- **Responsibility**:
  - Mix in `EventEmitterMixin` (alongside the existing `AbstractClient` bases).
  - Emit `BeforeClientCallEvent` / `AfterClientCallEvent` / `ClientCallFailedEvent` around `ask` (line 1286) / `ask_stream` (line 1324).
  - Emit `ClientStreamChunkEvent` per chunk (no bus forwarding unless explicit opt-in).
  - **Caveat**: `ask` / `ask_stream` are `@abstractmethod` in `AbstractClient`; concrete subclasses (`ClaudeClient`, `OpenAIClient`, etc.) implement them. The mixin must NOT redefine the abstract signatures — instead, emission happens via a thin sync wrapper added to the base that concrete subclasses call (`self._emit_before_call(...)` / `_emit_after_call(...)` / `_emit_failed_call(...)`), OR by wrapping inside each concrete subclass's `ask`/`ask_stream`. The implementer chooses the cleanest pattern in the first task and applies it consistently.
- **Depends on**: Module 8.

### Module 14: AbstractTool Integration
- **Path**: `packages/ai-parrot/src/parrot/tools/abstract.py` (MODIFIED)
- **Class**: `AbstractTool` (defined at line 71).
- **Responsibility**:
  - Mix in `EventEmitterMixin`.
  - Emit `BeforeToolCallEvent` / `AfterToolCallEvent` / `ToolCallFailedEvent` around `execute()` (line 375). The base `execute()` already pops `_permission_context` at line 391 and stores it on `self._current_pctx` (line 421) — emission happens in the same wrapper before / after the concrete `_execute()`.
  - Propagate `TraceContext` extracted from `self._current_pctx.trace_context` (creating a child span before delegating to `_execute()`).
- **Depends on**: Module 8.

### Module 15: PermissionContext Extension
- **Path**: `packages/ai-parrot/src/parrot/auth/permission.py` (MODIFIED)
- **Class**: `PermissionContext` (`@dataclass`, defined at line 79).
- **Responsibility**: Add `trace_context: Optional[TraceContext] = None` field. Place it between `channel` and `extra` so existing positional construction is unaffected. All existing call sites use keyword args or default `None`, so this is a non-breaking change.
- **Depends on**: Module 1.

### Module 16: BotManager / AgentRegistry YAML Integration
- **Path (entry point)**: `packages/ai-parrot/src/parrot/manager/manager.py` — `BotManager` class at line 89 (`load_bots()` / `_load_database_bots()`).
- **Path (parser)**: `packages/ai-parrot/src/parrot/registry/registry.py` — `AgentRegistry.load_agent_definitions()` plus `BotMetadata.get_instance()` (line 78–149). The YAML→`BotMetadata` field-merging logic lives here; the new `events:` block is parsed alongside `tools`, `model`, `vector_store_config`, etc.
- **Responsibility**:
  - Parse the `events:` block from agent YAML definitions.
  - Resolve `handler` / `provider` dotted paths (`module.path:ObjectName`).
  - Construct subscribers / providers and register them with the agent's `EventRegistry` at bot instantiation time.
  - Apply `where` filters and `forward_to_bus` flag per subscriber.
- **Depends on**: Modules 5, 7, 8.

### Module 17: Public exports
- **Path**: `packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py`
- **Responsibility**: Curate the public API surface (all events, `EventRegistry`, `EventProvider`, `TraceContext`, `get_global_registry`, `scope`, built-in subscribers).
- **Depends on**: All library modules (1–16).

### Module 18: End-to-End PoC Script
- **Path**: `packages/ai-parrot/examples/lifecycle_events_poc.py`
- **Responsibility**: Single runnable Python script that exercises the full lifecycle event system across five canonical scenarios. Serves three purposes simultaneously: (a) the post-implementation "did it actually work" check run manually before feature approval; (b) executable documentation for users learning the system; (c) the integration regression artifact in CI. Each scenario is independent and reports a clear `PASS` / `FAIL` / `SKIPPED` outcome; the script exits non-zero if any required scenario fails.

  **Scenarios:**

  1. **`scenario_basic_telemetry`** — Construct a minimal `AbstractBot` subclass with a mock LLM client and one trivial tool. Attach a `LoggingSubscriber`. Call `await bot.ask("…")`. Assert that the captured log records contain the expected sequence: `AgentInitialized → AgentConfigured → ToolManagerReady → BeforeInvoke → BeforeClientCall → AfterClientCall → BeforeToolCall → AfterToolCall → MessageAdded → AfterInvoke`.

  2. **`scenario_otel_spans`** — Same agent setup, but attach `OpenTelemetrySubscriber` with an `InMemorySpanExporter`. Assert the exported spans form a tree with `BeforeInvokeEvent` as the root span, and `BeforeClientCallEvent` and `BeforeToolCallEvent` as direct children. **`SKIPPED`** with a clear message if `opentelemetry-sdk` is not installed (raise `SkipScenario`, do not fail the run).

  3. **`scenario_a2a_trace_propagation`** — Construct `AgentA` and `AgentB`. Wrap `AgentB` as a tool consumed by `AgentA`. Call `await agent_a.ask("…")`. Assert that every event emitted by `AgentB` carries the same `trace_context.trace_id` as `AgentA`'s `BeforeInvokeEvent`, and that `AgentB`'s `BeforeInvokeEvent.trace_context.parent_span_id` matches `AgentA`'s `BeforeToolCallEvent.span_id`.

  4. **`scenario_yaml_declarative`** — Define an agent from an inline YAML string containing an `events:` block that declares a custom `EventProvider`. Construct the agent through `BotManager`. Call `await agent.ask("…")`. Assert the provider's callbacks received the events declared in YAML, respecting the `where` filter.

  5. **`scenario_subscriber_error_isolation`** — Attach a deliberately-failing subscriber to `BeforeInvokeEvent` plus a second well-behaved subscriber to the same event. Call `await bot.ask("…")`. Assert: (a) the agent's invocation completed normally; (b) a `SubscriberErrorEvent` reached the global registry; (c) the second subscriber still received the original `BeforeInvokeEvent`.

  **Script structure (skeleton):**
  ```python
  """End-to-end PoC for the Lifecycle Events System (FEAT-176).

  Usage:
      python packages/ai-parrot/examples/lifecycle_events_poc.py

  Exit code 0 if all required scenarios pass. Scenarios skipped due to
  missing optional dependencies do not contribute to the exit code.
  """
  import asyncio
  import sys
  from typing import Callable, Awaitable

  Scenario = Callable[[], Awaitable[tuple[bool, str]]]  # (ok, summary)

  class SkipScenario(Exception):
      """Raised by a scenario to mark itself as skipped (e.g. missing optional dep)."""

  SCENARIOS: dict[str, Scenario] = {
      "basic_telemetry":            scenario_basic_telemetry,
      "otel_spans":                 scenario_otel_spans,           # may SKIP
      "a2a_trace_propagation":      scenario_a2a_trace_propagation,
      "yaml_declarative":           scenario_yaml_declarative,
      "subscriber_error_isolation": scenario_subscriber_error_isolation,
  }

  async def main() -> int:
      results: dict[str, tuple[bool | None, str]] = {}
      for name, fn in SCENARIOS.items():
          print(f"▶ {name} …", flush=True)
          try:
              ok, summary = await fn()
              results[name] = (ok, summary)
              print(f"  {'✅ PASS' if ok else '❌ FAIL'} — {summary}")
          except SkipScenario as exc:
              results[name] = (None, f"SKIPPED: {exc}")
              print(f"  ⊘ SKIPPED — {exc}")
          except Exception as exc:
              results[name] = (False, f"CRASH: {type(exc).__name__}: {exc}")
              print(f"  ❌ CRASH — {type(exc).__name__}: {exc}")

      print("\n=== Summary ===")
      passed  = [n for n, (ok, _) in results.items() if ok is True]
      failed  = [n for n, (ok, _) in results.items() if ok is False]
      skipped = [n for n, (ok, _) in results.items() if ok is None]
      print(f"  passed:  {len(passed)}/{len(SCENARIOS)}")
      print(f"  failed:  {len(failed)}")
      print(f"  skipped: {len(skipped)}")
      return 1 if failed else 0

  if __name__ == "__main__":
      sys.exit(asyncio.run(main()))
  ```

  **Constraints:**
  - Each scenario function returns `(ok: bool, summary: str)` and may raise `SkipScenario("reason")` for optional-dependency cases.
  - Scenarios MUST be self-contained — no shared mutable state between them. Each constructs its own bot, registry, and subscribers within an `events.scope()` context manager to avoid global registry contamination.
  - No external infrastructure required: `EventBus` runs in in-memory mode (no Redis), the LLM client is mocked, no real HTTP calls.
  - The script must run in under 5 seconds on reference hardware.
  - Output is human-readable plain text; no JSON / structured logging in the PoC orchestration itself (the events it generates internally still use `navconfig.logging` of course).

- **Depends on**: All library modules (1–17).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_trace_context_new_root` | 1 | `new_root()` produces valid 32-char trace_id and 16-char span_id. |
| `test_trace_context_child` | 1 | `.child()` preserves `trace_id`, generates fresh `span_id`, sets `parent_span_id`. |
| `test_trace_context_traceparent_roundtrip` | 1 | `from_traceparent_header(ctx.to_traceparent_header()) == ctx`. |
| `test_trace_context_invalid_header` | 1 | Invalid `traceparent` header raises `ValueError`. |
| `test_lifecycle_event_frozen` | 2 | Mutation raises `FrozenInstanceError`. |
| `test_lifecycle_event_to_dict_strict` | 2 | Non-JSON-serializable field raises `TypeError`. |
| `test_lifecycle_event_to_dict_roundtrip` | 2 | `to_dict()` output is `json.dumps`-able. |
| `test_concrete_events_minimal` | 3 | Each concrete event class instantiates with required fields. |
| `test_registry_subscribe_dispatch` | 5 | Subscriber receives matching events only. |
| `test_registry_subclass_dispatch` | 5 | Subscribing to `LifecycleEvent` receives every event. |
| `test_registry_reverse_order_after` | 5 | `AfterToolCallEvent` callbacks run in reverse registration order. |
| `test_registry_reverse_order_failed` | 5 | `*Failed` event callbacks also run in reverse order. |
| `test_registry_normal_order_before` | 5 | `Before*` callbacks run in forward registration order. |
| `test_registry_where_filter` | 5 | Callback skipped when `where()` predicate returns False. |
| `test_registry_subscriber_exception_isolated` | 5 | Failing subscriber doesn't break other subscribers or the emit call. |
| `test_registry_subscriber_exception_meta_event` | 5 | `SubscriberErrorEvent` is emitted to the global registry. |
| `test_registry_no_recursive_meta_event` | 5 | A failing subscriber listening to `SubscriberErrorEvent` doesn't loop. |
| `test_registry_dual_emit_opt_in` | 5 | `forward_to_bus=False` → no bus call. `forward_to_bus=True` → bus call. |
| `test_registry_stream_chunk_never_auto_forward` | 5 | `ClientStreamChunkEvent` is NEVER forwarded to bus by default, even with subscriber `forward_to_bus=True` unless explicitly required. |
| `test_global_registry_singleton` | 6 | `get_global_registry()` returns same instance across calls. |
| `test_global_registry_scope_isolation` | 6 | Inside `scope()`, global is replaced. After exit, original is restored. |
| `test_global_registry_scope_nested` | 6 | Nested `scope()` blocks isolate correctly. |
| `test_event_provider_registers_callbacks` | 7 | `add_provider()` invokes `register()` and collects all subscription IDs. |
| `test_mixin_lazy_registry` | 8 | `self.events` is lazily created on first access. |
| `test_mixin_global_forwarding` | 8 | Every local emit also reaches the global registry (when enabled). |
| `test_mixin_global_forwarding_disabled` | 8 | `forward_to_global=False` → no global propagation. |
| `test_logging_subscriber_levels` | 9 | `LoggingSubscriber` respects configured log levels. |
| `test_otel_subscriber_span_creation` | 10 | `BeforeInvokeEvent` opens a span; `AfterInvokeEvent` closes it. |
| `test_otel_subscriber_failed_span_status` | 10 | `InvokeFailedEvent` sets span status to ERROR. |
| `test_webhook_subscriber_hmac` | 11 | Signature header matches HMAC-SHA256 of body with configured secret. |
| `test_webhook_subscriber_retry` | 11 | Transient 5xx triggers retry (bounded). |
| `test_abstract_bot_emits_agent_initialized` | 12 | Constructing a bot subclass emits `AgentInitializedEvent`. |
| `test_abstract_bot_emits_configured` | 12 | `await bot.configure()` emits `AgentConfiguredEvent`. |
| `test_abstract_bot_emits_status_changed` | 12 | Setting `bot.status = AgentStatus.RUNNING` emits `AgentStatusChangedEvent`. |
| `test_abstract_bot_legacy_trigger_event_routes` | 12 | Calling `_trigger_event("foo", x=1)` routes through new pipeline with deprecation warning. |
| `test_abstract_bot_legacy_add_event_listener_deprecation` | 12 | `add_event_listener()` emits `DeprecationWarning` but still functions. |
| `test_abstract_bot_ask_accepts_trace_context` | 12 | `await bot.ask(q, trace_context=ctx)` propagates `ctx` to emitted events. |
| `test_abstract_bot_ask_creates_root_when_no_trace` | 12 | Without explicit `trace_context`, a root `TraceContext` is created. |
| `test_abstract_client_emits_around_ask` | 13 | `client.ask()` emits Before / After in success path; Before / Failed on exception. |
| `test_abstract_tool_emits_around_execute` | 14 | `tool.execute()` emits Before / After in success path; Before / Failed on exception. |
| `test_abstract_tool_propagates_trace_context_from_pctx` | 14 | `TraceContext` in `permission_context` is used as parent for the tool's span. |
| `test_botmanager_yaml_subscribers_loaded` | 16 | Agent YAML `events:` block produces a registry with the declared subscribers. |
| `test_botmanager_yaml_where_filter_applied` | 16 | `where:` clause in YAML translates to predicate filter at subscribe time. |

### Integration Tests

| Test | Description |
|---|---|
| `test_end_to_end_event_chain` | Real `AbstractBot` subclass with a real mock LLM client + 1 tool — verify the full sequence: `AgentInitialized → AgentConfigured → ToolManagerReady → BeforeInvoke → BeforeClientCall → AfterClientCall → BeforeToolCall → AfterToolCall → MessageAdded → AfterInvoke`. |
| `test_trace_context_propagation_full_chain` | Same flow as above — verify every event shares the same `trace_id`. Verify `BeforeToolCallEvent.trace_context.parent_span_id == BeforeInvokeEvent.trace_context.span_id`. |
| `test_a2a_trace_context_propagation` | Agent A (root span) invokes Agent B wrapped as a tool. Agent B's `BeforeInvokeEvent.trace_context.trace_id == AgentA.BeforeInvokeEvent.trace_context.trace_id`. Agent B's `parent_span_id` corresponds to AgentA's `BeforeToolCallEvent.span_id`. |
| `test_event_bus_distributed_dispatch` | Two `EventRegistry` instances share an `EventBus`. Subscriber on registry 2 receives events emitted by registry 1 via the bus. |
| `test_failed_subscriber_emits_meta_event` | Subscriber that raises → `SubscriberErrorEvent` appears in the global registry. Other subscribers in the same chain still run. |
| `test_scope_isolation_in_pytest` | Two parallel tests using `scope()` do not see each other's global subscribers. |
| `test_invoke_failed_skips_after_invoke` | When the LLM client raises, `InvokeFailedEvent` is emitted and `AfterInvokeEvent` is NOT emitted. |
| `test_yaml_loaded_subscribers_receive_events` | Load agent from YAML with declared `LoggingSubscriber`; perform an `ask()`; verify the logger received the expected log records. |
| `test_opentelemetry_subscriber_export` | With an in-memory OTel exporter, verify spans are created for the full invoke → client → tool chain with proper parent-child relationships. |
| `test_stream_chunk_event_no_bus_pressure` | 1000-chunk streaming response emits 1000 `ClientStreamChunkEvent` to local subscribers but ZERO `EventBus.emit` calls (verified via spy). |

### Test Data / Fixtures

```python
@pytest.fixture
def trace_root() -> TraceContext:
    return TraceContext.new_root()

@pytest.fixture
def empty_registry() -> EventRegistry:
    return EventRegistry(forward_to_global=False)

@pytest.fixture
def isolated_global():
    """Reset global registry around each test."""
    with scope() as reg:
        yield reg

@pytest.fixture
def mock_event_bus():
    """An in-memory EventBus with spy on .emit()."""
    bus = EventBus(use_redis=False)
    bus.emit = AsyncMock(wraps=bus.emit)
    return bus

@pytest.fixture
def captured_events():
    """A subscriber that captures every event for assertion."""
    captured: list[LifecycleEvent] = []
    async def _capture(evt: LifecycleEvent) -> None:
        captured.append(evt)
    return captured, _capture
```

---

## 5. Acceptance Criteria

This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/unit/events/lifecycle/ -v`).
- [ ] All integration tests pass (`pytest packages/ai-parrot/tests/integration/events/ -v`).
- [ ] Existing test suite continues to pass (`pytest packages/ai-parrot/tests/ -v`) — zero regressions.
- [ ] Public API documented in `packages/ai-parrot/docs/lifecycle_events.md`, including: data model overview, registry API, TraceContext semantics, YAML syntax, subscriber catalog, migration guide from `_trigger_event`.
- [ ] No breaking changes to existing public API. `_trigger_event` and `add_event_listener` continue to work, emit `DeprecationWarning`, and route through the new pipeline.
- [ ] `AbstractBot.ask` / `ask_stream` / `conversation` accept an optional `trace_context: TraceContext | None = None` parameter; default behavior unchanged.
- [ ] All 15 concrete event classes are `@dataclass(frozen=True)`; mutation attempts raise `FrozenInstanceError` (covered by tests).
- [ ] `event.to_dict()` raises `TypeError` for non-JSON-serializable fields — strict mode (covered by tests).
- [ ] Subscriber exceptions never propagate; `SubscriberErrorEvent` emitted to global registry (covered by tests).
- [ ] `ClientStreamChunkEvent` never reaches `EventBus` by default; explicit opt-in required (covered by `test_stream_chunk_event_no_bus_pressure`).
- [ ] `opentelemetry-api` and `opentelemetry-sdk` declared in `extras_require['otel']`; importing `OpenTelemetrySubscriber` without them raises a clear `ImportError`.
- [ ] `python packages/ai-parrot/examples/lifecycle_events_poc.py` exits with code 0; scenarios 1, 3, 4, and 5 report `PASS`. Scenario 2 reports `PASS` when `opentelemetry-sdk` is installed, `SKIPPED` otherwise (never `FAIL` for missing optional deps).
- [ ] PoC scenarios 1, 3, 4, and 5 run successfully without Redis and without the `otel` extra installed.
- [ ] Performance benchmark: emitting 10,000 events with 5 subscribers each completes in < 500 ms on reference hardware (single-process, no bus, no OTel).
- [ ] Performance benchmark: dual-emit overhead for a single event with no bus subscribers is < 50 µs (measured by `pytest-benchmark` using `loop.run_until_complete()` to avoid `asyncio.run()` loop-creation overhead of ~200–500 µs on CPython 3.11). The original < 10 µs target assumed a persistent loop; measured baseline on CPython 3.11 (Intel i7, no OTel, no bus) is ~5–15 µs. The threshold is set at 50 µs to account for CI hardware variance.
- [ ] All open questions in §8 resolved.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# Existing — verified by grep/read of packages/ai-parrot/src
from parrot.core.events.evb import EventBus, Event, EventSubscription, EventPriority
# Source: packages/ai-parrot/src/parrot/core/events/evb.py

from parrot.core.hooks.base import BaseHook
from parrot.core.hooks.manager import HookManager
from parrot.core.hooks.mixins import HookableAgent
from parrot.core.hooks.models import HookEvent, HookType
# Source: packages/ai-parrot/src/parrot/core/hooks/{base,manager,mixins}.py
# NOTE: These are EXTERNAL trigger hooks, NOT to be confused with this feature.

from parrot.bots.abstract import AbstractBot
# Source: packages/ai-parrot/src/parrot/bots/abstract.py

from parrot.clients.base import AbstractClient
# Source: packages/ai-parrot/src/parrot/clients/base.py (class at line 233)

from parrot.tools.abstract import AbstractTool
# Source: packages/ai-parrot/src/parrot/tools/abstract.py (class at line 71)

from parrot.tools.toolkit import AbstractToolkit
# Source: packages/ai-parrot/src/parrot/tools/toolkit.py

from parrot.auth.permission import PermissionContext
# Source: packages/ai-parrot/src/parrot/auth/permission.py (dataclass at line 79)

from parrot.models.status import AgentStatus
# Source: packages/ai-parrot/src/parrot/models/status.py (members: IDLE, WORKING, COMPLETED, FAILED)
# NOTE: A second AgentStatus exists in parrot/a2a/mesh.py:57 — DO NOT use it for bot lifecycle.

from parrot.manager.manager import BotManager
from parrot.registry.registry import AgentRegistry, BotMetadata
# Source: packages/ai-parrot/src/parrot/{manager/manager.py, registry/registry.py}

from navconfig.logging import logging
# Standard project logging pattern (used throughout the codebase).
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/core/events/evb.py
class EventPriority(Enum):
    LOW = 0
    NORMAL = 5
    HIGH = 10
    CRITICAL = 15

@dataclass
class Event:
    event_type: str
    payload: dict[str, Any]
    event_id: str
    timestamp: datetime
    source: Optional[str]
    priority: EventPriority
    correlation_id: Optional[str]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event": ...

@dataclass
class EventSubscription:
    pattern: str
    handler: Callable[[Event], Any]
    subscriber_id: str
    priority: int
    filter_fn: Optional[Callable[[Event], bool]]
    async_handler: bool

class EventBus:
    CHANNEL_PREFIX = "parrot:events:"
    def __init__(self, redis_url: Optional[str] = None, use_redis: bool = False) -> None: ...
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    def subscribe(
        self,
        pattern: str,
        handler: Callable[[Event], Any],
        *,
        priority: int = 0,
        filter_fn: Optional[Callable[[Event], bool]] = None,
    ) -> str: ...
    # NOTE: `.emit()` method is referenced by HookManager._dual_emit;
    # implementer MUST verify exact signature before use (see §8 Open Questions).
```

```python
# packages/ai-parrot/src/parrot/bots/abstract.py — partial, lines approximate
class AbstractBot(DBInterface, LocalKBMixin, ABC):
    EVENT_STATUS_CHANGED: str  # class-level constant
    _listeners: dict[str, list[Callable]]
    _status: AgentStatus
    name: str
    logger: logging.Logger

    @property
    def status(self) -> AgentStatus: ...
    @status.setter
    def status(self, value: AgentStatus) -> None:
        # Currently calls self._trigger_event(self.EVENT_STATUS_CHANGED, ...)
        ...

    def add_event_listener(self, event_name: str, callback: Callable) -> None: ...
    def _trigger_event(self, event_name: str, **kwargs) -> None: ...

    @property
    def system_prompt(self) -> str: ...
    @system_prompt.setter
    def system_prompt(self, value: str) -> None: ...

    def define_store_config(self) -> Optional[StoreConfig]: ...
    def register_kb(self, kb: AbstractKnowledgeBase) -> None: ...
    # Methods to extend (signatures to be verified by implementer):
    # async def ask(self, question: str, ...) -> AIMessage
    # async def ask_stream(self, question: str, ...)
    # async def conversation(self, ...)
    # async def configure(self, ...) -> None
```

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):
    async def _pre_execute(self, name: str, **kwargs: Any) -> None: ...
    async def _post_execute(self, name: str, result: Any, **kwargs: Any) -> Any: ...
    # _post_execute receives only tool params (no _permission_context).
    # _pre_execute receives _permission_context kwarg (may be None).

# In toolkit.py, the tool wrapper for bound methods:
# - Strips _permission_context before validation
# - Re-injects via instance variable _current_pctx for _pre_execute
# - Result transformation happens in _post_execute
```

```python
# packages/ai-parrot/src/parrot/core/hooks/manager.py — REFERENCE PATTERN ONLY
# HookManager._dual_emit demonstrates the dual-emit pattern that
# EventRegistry will replicate. Read it for inspiration but DO NOT
# import or extend it for this feature.
# Confirmed (verified at line ~87): _dual_emit calls
#   await bus.emit(f"hooks.{hook_type.value}.{event_type}", event.model_dump())
# matching the EventBus.emit signature below.
```

```python
# packages/ai-parrot/src/parrot/core/events/evb.py — EventBus.emit signature (verified)
class EventBus:
    async def emit(
        self,
        event_type: str,           # hierarchical dotted string, e.g. "lifecycle.BeforeInvokeEvent"
        payload: dict[str, Any],   # JSON-serializable dict (event.to_dict() output)
        **kwargs,
    ) -> int:                       # returns count of handlers that processed the event
        ...
```

```python
# packages/ai-parrot/src/parrot/clients/base.py — AbstractClient (verified)
class AbstractClient(ABC):
    def __init__(
        self,
        conversation_memory: Optional[ConversationMemory] = None,
        preset: Optional[str] = None,
        tools: Optional[List[Union[str, AbstractTool]]] = None,
        use_tools: bool = False,
        debug: bool = True,
        tool_manager: Optional[ToolManager] = None,
        **kwargs,
    ): ...

    @abstractmethod
    async def ask(
        self,
        prompt: str,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        ...
    ) -> MessageResponse: ...

    @abstractmethod
    async def ask_stream(
        self,
        prompt: str,
        model: str = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        ...
    ) -> AsyncIterator[Union[str, AIMessage]]: ...
```

```python
# packages/ai-parrot/src/parrot/tools/abstract.py — AbstractTool (verified)
class AbstractTool(ABC):
    def __init__(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        output_dir: Optional[Union[str, Path]] = None,
        base_url: Optional[str] = None,
        static_dir: Optional[Union[str, Path]] = None,
        routing_meta: Optional[Dict] = None,
        **kwargs,
    ): ...

    async def execute(self, *args, **kwargs) -> ToolResult:
        # line 391:  pctx = kwargs.pop('_permission_context', None)
        # line 392:  resolver = kwargs.pop('_resolver', None)
        # line 421:  self._current_pctx = pctx     # available to _pre_execute / lifecycle hooks
        # then calls self._execute(*args, **kwargs)
        ...

    @abstractmethod
    async def _execute(self, *args, **kwargs) -> ToolResult: ...
```

```python
# packages/ai-parrot/src/parrot/auth/permission.py — PermissionContext (verified)
@dataclass
class PermissionContext:
    session: UserSession
    request_id: Optional[str] = None
    channel: Optional[str] = None
    # ←── FEAT-176 adds here: trace_context: Optional["TraceContext"] = None
    extra: dict[str, Any] = field(default_factory=dict)
```

```python
# packages/ai-parrot/src/parrot/models/status.py — AgentStatus (verified)
class AgentStatus(Enum):
    IDLE = "idle"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
# AgentStatusChangedEvent.old_status / new_status hold the .name string ("IDLE", "WORKING", ...).
```

```python
# packages/ai-parrot/src/parrot/bots/abstract.py — AbstractBot.add_turn (verified, line 1410)
async def add_turn(
    self,
    user_id: str,
    session_id: str,
    turn: ConversationTurn,
    chatbot_id: Optional[str] = None,
) -> None:
    """Canonical insertion point for conversation history.

    Emit MessageAddedEvent here (and ONLY here) so every code path
    (ask, ask_stream, conversation, and concrete bot subclasses) is
    covered by a single emission site. Concrete subclasses
    (BasicBot, Chatbot, ...) call self.add_turn(...) — verify in
    the subclass during implementation to confirm coverage.
    """
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `EventRegistry.emit` | `EventBus.emit` | method call | `packages/ai-parrot/src/parrot/core/hooks/manager.py:_dual_emit` (reference) |
| `EventEmitterMixin._init_events` | `AbstractBot.__init__` | mixin attachment | `packages/ai-parrot/src/parrot/bots/abstract.py:__init__` |
| `EventEmitterMixin._init_events` | `AbstractTool.__init__` | mixin attachment | `packages/ai-parrot/src/parrot/tools/abstract.py:91` |
| `EventEmitterMixin._init_events` | `AbstractClient.__init__` | mixin attachment | `packages/ai-parrot/src/parrot/clients/base.py:263` |
| `EventRegistry` ← `_trigger_event` | `AbstractBot._trigger_event` (rerouted) | internal | `packages/ai-parrot/src/parrot/bots/abstract.py:_trigger_event` |
| `AgentStatusChangedEvent` | `AbstractBot.status.setter` | emit on change | `packages/ai-parrot/src/parrot/bots/abstract.py:status.setter` |
| `MessageAddedEvent` | `AbstractBot.add_turn` | emit on insert | `packages/ai-parrot/src/parrot/bots/abstract.py:1410` |
| `BotManager YAML loader` | new `events:` block | parser extension | `packages/ai-parrot/src/parrot/manager/manager.py:89` (entry) + `packages/ai-parrot/src/parrot/registry/registry.py:78` (`BotMetadata.get_instance`) |
| `TraceContext` ← `permission_context` | propagation field | dataclass extension | `packages/ai-parrot/src/parrot/auth/permission.py:79` |
| `AgentStatusChangedEvent` ← status enum | enum lookup | `.name` string | `packages/ai-parrot/src/parrot/models/status.py` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.core.events.lifecycle.*`~~ — this is what we are creating; no prior version exists.
- ~~`parrot.events`~~ — top-level `parrot.events` package does NOT exist. Use `parrot.core.events`.
- ~~`AbstractBot.events`~~ — property does not exist yet; we are adding it.
- ~~`AbstractBot.subscribe`~~ — method does not exist; subscription happens via `self.events.subscribe(...)`.
- ~~`EventBus.lifecycle_emit`~~ — no such convenience method; we use plain `EventBus.emit`.
- ~~`TraceContext`~~ — class does not exist anywhere in the codebase; we are introducing it.
- ~~`OpenTelemetrySubscriber`~~ — not present.
- ~~`LoggingSubscriber`~~ — not present (`navconfig.logging` is used directly today).
- ~~`HookManager.lifecycle`~~ — `HookManager` is for external triggers; do NOT extend it for this feature.
- ~~`BaseHook` as a parent for lifecycle events~~ — `BaseHook` is the *external trigger* abstraction. Lifecycle events have no parent in that hierarchy.
- ~~`@on_event` / `@emit_event` decorators~~ — the December 2025 brainstorm proposed these; they are NOT implemented and NOT part of this spec.
- ~~`EventEmitterMixin` in any existing module~~ — name is reserved by this spec; verify via `grep -r EventEmitterMixin packages/ai-parrot/src` before creation.
- ~~`event.cancel()` / `event.retry` / `event.selected_tool`~~ — these are *interceptor* concerns (Strands), explicitly OUT OF SCOPE for Phase 1.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **`@dataclass(frozen=True)`** for every event class — never `Pydantic` models. Performance matters in the hot path; frozen dataclasses are ~5× faster to instantiate than Pydantic v2 models, and immutability is the design contract. (Pydantic v2 is used elsewhere in AI-Parrot for I/O boundaries; events are internal.)
- **Async-first throughout** — all subscriber callbacks are `Callable[[E], Awaitable[None]]`. No sync support.
- **`navconfig` for environment** — `OTEL_EXPORTER_OTLP_ENDPOINT`, `EVENTS_WEBHOOK_SECRET`, etc. must be read via `navconfig.config`, never `os.environ` directly.
- **Lazy imports for OTel** — `opentelemetry.*` imports MUST live inside the `OpenTelemetrySubscriber` class body or methods, never at module top level. If the user doesn't install the `otel` extra, the rest of the system must continue to work.
- **`navconfig.logging` for all logging** — `logger = logging.getLogger("parrot.core.events.lifecycle.<submodule>")`.
- **`contextvars.ContextVar`** for the global registry, not module-level globals — to ensure task-safety under asyncio.
- **Strict JSON serialization** — `LifecycleEvent.to_dict` must call `json.dumps` internally as a validation step and re-raise as `TypeError` with a clear message identifying the offending field.

### Known Risks / Gotchas

- **Risk: Backward-compat surface area.** `_trigger_event` is called internally in `AbstractBot.status.setter`. Rerouting it through the new pipeline must preserve the exact same observable side effects for code subscribed via `add_event_listener`. **Mitigation:** add a `_LegacyEventBridge` subscriber that converts new typed events back to legacy string-keyed callbacks on the old `_listeners` dict.

- **Risk: Performance regression in tight loops.** Streaming responses can emit thousands of `ClientStreamChunkEvent`s per second. **Mitigation:** (a) never auto-forward stream chunks to `EventBus`; (b) check for zero subscribers and short-circuit before constructing the event; (c) include a `pytest-benchmark` baseline in the test suite.

- **Risk: Reverse ordering for `After*`/`*Failed` events surprises users.** **Mitigation:** documented explicitly in `lifecycle_events.md` with the cleanup-symmetry rationale; cover with a dedicated test (`test_registry_reverse_order_after`).

- **Risk: Global registry test contamination.** Tests that subscribe to the global registry pollute subsequent tests. **Mitigation:** mandatory `isolated_global` fixture pattern; document in CONTRIBUTING.

- **Risk: `permission_context` extension breaks existing call sites.** `trace_context` field must be optional with a default of `None`. **Mitigation:** verify before merge that every existing `permission_context` construction works without modification (run full integration suite).

- **Risk: Circular import between `EventRegistry` and `EventBus`.** `EventBus` doesn't depend on lifecycle, but `EventRegistry` depends on `EventBus`. **Mitigation:** one-directional dependency only; verify via `python -c "from parrot.core.events.lifecycle import *"` doesn't trigger ImportError.

- **Risk: A2A trace context propagation depends on `permission_context` reaching the sub-agent.** When AgentA invokes AgentB as a tool, the `permission_context` is passed through the toolkit wrapper. **Mitigation:** add an explicit integration test (`test_a2a_trace_context_propagation`) and document the contract.

### External Dependencies

| Package | Version | Reason | Where |
|---|---|---|---|
| `opentelemetry-api` | `>=1.25` | OTel span creation | `extras_require['otel']` |
| `opentelemetry-sdk` | `>=1.25` | OTel SDK for span export | `extras_require['otel']` |
| (no new core deps) | — | All other dependencies (`aiohttp`, `navconfig`, stdlib `dataclasses`, `contextvars`, `uuid`, `hashlib`) are already project dependencies. | — |

---

## 8. Open Questions

> Questions Q1–Q7 and Q9 were resolved during the spec→task hand-off (2026-05-15) via direct grep/read against `packages/ai-parrot/src/`. Q8 and Q10 remain open for Jesus's call.

- [x] **Q1 — `AbstractClient` exact path. RESOLVED.** `packages/ai-parrot/src/parrot/clients/base.py`, class `AbstractClient` at line 233. `__init__` at line 263. `ask` (abstract) at line 1286. `ask_stream` (abstract) at line 1324. See §6 for verified signatures and the Module 13 caveat about emission via thin sync wrappers vs concrete-subclass wrappers.

- [x] **Q2 — `AbstractTool` exact path. RESOLVED.** `packages/ai-parrot/src/parrot/tools/abstract.py`, class `AbstractTool` at line 71. `__init__` at line 91. `execute()` wrapper at line 375 (concrete subclasses override `_execute`). Tools already pop `_permission_context` (line 391) and store it on `self._current_pctx` (line 421), so trace propagation hooks into an existing channel.

- [x] **Q3 — `permission_context` data structure location. RESOLVED.** `packages/ai-parrot/src/parrot/auth/permission.py`, `@dataclass PermissionContext` at line 79. Add `trace_context: Optional[TraceContext] = None` between `channel` and `extra` — non-breaking because all existing call sites use keyword args.

- [x] **Q4 — `BotManager` YAML loader path. RESOLVED.** Entry point: `packages/ai-parrot/src/parrot/manager/manager.py` (`BotManager.load_bots()` / `_load_database_bots()`, class at line 89). YAML→`BotMetadata` field-merging logic: `packages/ai-parrot/src/parrot/registry/registry.py` (`AgentRegistry.load_agent_definitions()` + `BotMetadata.get_instance()` lines 78–149). Add `events:` block parsing alongside `tools` / `model` / `vector_store_config` in the registry's field merge.

- [x] **Q5 — `EventBus.emit` signature. RESOLVED.** Method exists with signature `async def emit(self, event_type: str, payload: dict[str, Any], **kwargs) -> int` in `packages/ai-parrot/src/parrot/core/events/evb.py` (line ~291). Returns the count of handlers that processed the event. `HookManager._dual_emit` (line ~87) uses it as the spec assumed — no adapter shim required. Channel format: `f"lifecycle.{event_class_name}"`, payload from `event.to_dict()`.

- [x] **Q6 — Status taxonomy. RESOLVED.** `parrot/models/status.py` defines `AgentStatus(Enum)` with members `IDLE = "idle"`, `WORKING = "working"`, `COMPLETED = "completed"`, `FAILED = "failed"`. Serialize as `.name` (the uppercase identifier) in `AgentStatusChangedEvent`. NOTE: a second `AgentStatus` exists in `parrot/a2a/mesh.py:57` — do NOT use it for bot lifecycle events.

- [x] **Q7 — Conversation history insertion point. RESOLVED.** `AbstractBot.add_turn` at `packages/ai-parrot/src/parrot/bots/abstract.py:1410` is the canonical insertion site. Emit `MessageAddedEvent` from inside `add_turn` (and only there) so every concrete bot (`BasicBot`, `Chatbot`, …) is covered by a single emission point. Implementer must spot-check that `ask` / `ask_stream` / `conversation` in concrete subclasses call `self.add_turn(...)` rather than writing to history directly.

- [ ] **Q8 — Should `EventRegistry` instances be per-conversation or per-bot-instance?** Current design says per-bot. A future user-isolation concern (one bot serving many users) might require per-conversation registries. Defer to Phase 1.5 unless an immediate need surfaces. *Owner: Jesus — still open, defer-or-confirm.*: for this phase, a EventRegistry per-bot instance.

- [x] **Q9 — Sync emit fallback for non-async callers. RESOLVED.** No `emit_sync` public API. In sync contexts (`AbstractBot.status.setter`, `__init__` paths) use the helper `self.events.emit_nowait(evt)` defined on `EventRegistry`, which internally:
  1. Tries `asyncio.get_running_loop()`.
  2. If a loop is running → `loop.create_task(self.emit(evt), name=f"lifecycle.{type(evt).__name__}")`.
  3. If no loop is running (e.g. early `__init__` before the bot enters async land) → logs at DEBUG and drops the event. Lifecycle events are observability-only; dropping a startup event when there's no consumer loop is acceptable.
  Document this gotcha in `lifecycle_events.md`.

- [x] **Q10 — Strict version pin for OTel.** `>=1.25` is conservative. Should we pin a maximum to avoid future breakage? *Owner: Jesus — still open.*: Agree.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-15 | Jesus Lara | Initial draft from cross-conversation design (Dec 2025 brainstorm + May 2026 refinement based on Strands Agents hooks pattern). Phase 1 scope only (observability, no interceptors, no crew events). |
| 0.2 | 2026-05-15 | Jesus Lara | Added Module 18: end-to-end PoC script in `examples/lifecycle_events_poc.py` covering 5 canonical scenarios (basic telemetry, OTel spans, A2A trace propagation, YAML declarative loading, subscriber error isolation) as the post-implementation validation deliverable. Refined Module 17 dependency wording for disambiguation. Added 2 acceptance-criteria items for PoC validation. |
| 0.3 | 2026-05-15 | Jesus Lara | Pre-task-decomposition cleanup: resolved Q1–Q7 and Q9 in §8 by verifying paths/signatures against the codebase. Modules 13–16 updated with confirmed paths (`parrot/clients/base.py`, `parrot/tools/abstract.py`, `parrot/auth/permission.py`, `parrot/manager/manager.py` + `parrot/registry/registry.py`). §6 Codebase Contract gained verified imports and signatures for `AbstractClient`, `AbstractTool`, `PermissionContext`, `AgentStatus`, `AbstractBot.add_turn`, and `EventBus.emit`. Q8 and Q10 remain open. |
