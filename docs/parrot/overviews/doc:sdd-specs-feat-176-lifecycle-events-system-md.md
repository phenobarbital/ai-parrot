---
type: Wiki Overview
title: 'Feature Specification: Lifecycle Events System'
id: doc:sdd-specs-feat-176-lifecycle-events-system-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'AI-Parrot currently lacks a structured observability layer for agent execution.
  The existing mechanism — `AbstractBot._trigger_event()` / `add_event_listener()`
  — is:'
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.auth.permission
  rel: mentions
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.clients.base
  rel: mentions
- concept: mod:parrot.core.events
  rel: mentions
- concept: mod:parrot.core.events.evb
  rel: mentions
- concept: mod:parrot.core.events.lifecycle
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.subscribers
  rel: mentions
- concept: mod:parrot.core.hooks
  rel: mentions
- concept: mod:parrot.core.hooks.base
  rel: mentions
- concept: mod:parrot.core.hooks.manager
  rel: mentions
- concept: mod:parrot.core.hooks.mixins
  rel: mentions
- concept: mod:parrot.core.hooks.models
  rel: mentions
- concept: mod:parrot.manager.manager
  rel: mentions
- concept: mod:parrot.models.status
  rel: mentions
- concept: mod:parrot.registry.registry
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_tools
  rel: mentions
---

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

…(truncated)…
