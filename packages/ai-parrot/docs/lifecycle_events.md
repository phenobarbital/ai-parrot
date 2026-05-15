# Lifecycle Events System

AI-Parrot emits **typed, frozen events** at key execution points: before and
after an invocation, before and after a tool call, on LLM client calls, and
on agent status changes. Subscribers are async callbacks that receive a
fully-populated event object — they cannot modify the event or cancel the
underlying operation.

The system is observability-first: it is designed for telemetry, auditing,
and debugging, not for altering bot behavior. Every event carries a
`TraceContext` that links related events across agents, tools, and LLM calls
into a single distributed trace.

For the technical specification see
`sdd/specs/FEAT-176-lifecycle-events-system.md`.

---

## Table of contents

1. [Quickstart](#1-quickstart)
2. [Event catalog](#2-event-catalog)
3. [Registry API](#3-registry-api)
4. [TraceContext semantics](#4-tracecontext-semantics)
5. [Global registry and scope()](#5-global-registry-and-scope)
6. [Dispatch ordering](#6-dispatch-ordering)
7. [Error isolation](#7-error-isolation)
8. [Dual-emit to EventBus](#8-dual-emit-to-eventbus)
9. [YAML declarative syntax](#9-yaml-declarative-syntax)
10. [Built-in subscribers](#10-built-in-subscribers)
11. [emit_nowait gotcha](#11-emit_nowait-gotcha)
12. [Migration guide](#12-migration-guide-from-_trigger_event--add_event_listener)
13. [What is not here yet](#13-what-is-not-here-yet)

---

## 1. Quickstart

```python
import asyncio
from parrot.core.events.lifecycle import (
    scope, BeforeInvokeEvent, AfterInvokeEvent,
)

async def main():
    async def on_start(evt: BeforeInvokeEvent) -> None:
        print(f"[{evt.trace_context.trace_id}] {evt.agent_name}.{evt.method}()")

    async def on_end(evt: AfterInvokeEvent) -> None:
        print(f"  -> done in {evt.duration_ms:.1f} ms")

    # scope() creates an isolated registry — safe for scripts and tests.
    with scope() as registry:
        registry.subscribe(BeforeInvokeEvent, on_start)
        registry.subscribe(AfterInvokeEvent, on_end)

        from my_app import bot        # your AbstractBot subclass
        await bot.ask("hello world")

asyncio.run(main())
```

`scope()` is optional in production. When you call `bot.events.subscribe()`
directly, subscriptions are scoped to that bot instance and also forwarded
to the process-wide global registry (unless `forward_to_global=False`).

---

## 2. Event catalog

All event classes are in `parrot.core.events.lifecycle` (public API) or
importable from `parrot.core.events.lifecycle.events`. Every event inherits
`LifecycleEvent` which provides `trace_context: TraceContext` and
`emitted_at: float` (Unix timestamp).

### Agent lifecycle

| Event class | When emitted | Key fields |
|---|---|---|
| `AgentInitializedEvent` | After `AbstractBot.__init__` completes | `agent_name`, `agent_class` |
| `AgentConfiguredEvent` | After LLM client + vector store are wired | `agent_name`, `llm_provider`, `llm_model`, `has_vector_store` |
| `ToolManagerReadyEvent` | After tools are loaded | `agent_name`, `tool_count`, `tool_names: tuple[str, ...]` |
| `AgentStatusChangedEvent` | On every `bot.status = ...` assignment | `agent_name`, `old_status`, `new_status` |

### Invocation lifecycle

| Event class | When emitted | Key fields |
|---|---|---|
| `BeforeInvokeEvent` | Before `ask` / `ask_stream` / `conversation` | `agent_name`, `method`, `question`, `user_id`, `session_id` |
| `AfterInvokeEvent` | After successful return | `agent_name`, `method`, `duration_ms`, `input_tokens`, `output_tokens` |
| `InvokeFailedEvent` | On unhandled exception in `ask` / `ask_stream` | `agent_name`, `method`, `duration_ms`, `error_type`, `error_message` |

### LLM client lifecycle

| Event class | When emitted | Key fields |
|---|---|---|
| `BeforeClientCallEvent` | Before sending to LLM provider | `client_name`, `model`, `temperature`, `system_prompt_hash`, `has_tools` |
| `AfterClientCallEvent` | After successful response | `client_name`, `model`, `duration_ms`, `input_tokens`, `output_tokens`, `finish_reason` |
| `ClientCallFailedEvent` | On LLM API error | `client_name`, `model`, `duration_ms`, `error_type`, `error_message` |
| `ClientStreamChunkEvent` | Per chunk during streaming | `client_name`, `model`, `chunk_index`, `chunk_size_bytes` |

> `ClientStreamChunkEvent` is **high-frequency**. It never auto-forwards to
> `EventBus` to avoid bus pressure. Opt-in explicitly with
> `forward_to_bus=True` on the subscription.

### Tool lifecycle

| Event class | When emitted | Key fields |
|---|---|---|
| `BeforeToolCallEvent` | Before `AbstractTool.execute()` | `tool_name`, `tool_class`, `args_summary: dict` |
| `AfterToolCallEvent` | After successful tool return | `tool_name`, `duration_ms`, `result_status`, `result_size_bytes` |
| `ToolCallFailedEvent` | On tool exception | `tool_name`, `duration_ms`, `error_type`, `error_message` |

### Message lifecycle

| Event class | When emitted | Key fields |
|---|---|---|
| `MessageAddedEvent` | When a message is appended to conversation history | `agent_name`, `role`, `content_length`, `has_tool_calls` |

### Meta

| Event class | When emitted | Key fields |
|---|---|---|
| `SubscriberErrorEvent` | When any subscriber raises | `failed_subscriber`, `original_event_class`, `error_type`, `error_message`, `traceback` |

`SubscriberErrorEvent` is always emitted on the **global registry**, never on
the per-bot registry that triggered the failing subscriber.

---

## 3. Registry API

Every `AbstractBot`, `AbstractClient`, and `AbstractTool` instance exposes
`self.events: EventRegistry`. You can also get the process-wide singleton via
`get_global_registry()`.

### subscribe

```python
subscription_id: str = registry.subscribe(
    event_type,          # Type[E] — e.g. BeforeInvokeEvent
    callback,            # async def cb(event: E) -> None
    where=None,          # Optional[Callable[[E], bool]] — predicate filter
    forward_to_bus=False,# bool — dual-emit to EventBus
)
```

`event_type` uses `isinstance` matching: subscribing to `LifecycleEvent`
receives ALL events; subscribing to `BeforeToolCallEvent` receives only that.

The `where` predicate is called on each candidate event before the callback.
Returning `False` skips the callback silently.

```python
# Only fire for specific tools
registry.subscribe(
    BeforeToolCallEvent,
    my_cb,
    where=lambda e: e.tool_name in {"jira_create", "jira_update"},
)
```

### unsubscribe

```python
removed: bool = registry.unsubscribe(subscription_id)
```

Returns `True` if the subscription existed and was removed.

### add_provider

```python
ids: list[str] = registry.add_provider(provider)
```

`provider` must implement `EventProvider` (see [YAML declarative
syntax](#9-yaml-declarative-syntax)). Calls `provider.register(registry)`,
which should call `registry.subscribe(...)` as many times as needed.

### emit (async)

```python
await registry.emit(event)
```

Dispatches the event. Never raises — subscriber exceptions are isolated (see
[Error isolation](#7-error-isolation)).

### emit_nowait (sync, requires running event loop)

```python
registry.emit_nowait(event)
```

Schedules the event as an `asyncio.Task`. Fires when the event loop yields
(before the next `await`). **Do not call from a thread without a running
loop** — the event will be silently dropped. See
[emit_nowait gotcha](#11-emit_nowait-gotcha).

### has_subscribers

```python
registry.has_subscribers(event_type) -> bool
```

Returns `True` if any subscriber would match the given event type. Use this
to short-circuit expensive event construction on hot paths (e.g., inside
streaming loops).

---

## 4. TraceContext semantics

`TraceContext` is a frozen dataclass with W3C Trace Context compatible fields:

```python
from parrot.core.events.lifecycle import TraceContext

tc = TraceContext.new_root()   # creates a new root span (random trace_id + span_id)
child_tc = tc.child()          # creates a child span (same trace_id, new span_id,
                                # parent_span_id = tc.span_id)
```

Fields:

| Field | Type | Description |
|---|---|---|
| `trace_id` | `str` | 16-byte hex (32 chars). Shared across all spans in a trace. |
| `span_id` | `str` | 8-byte hex (16 chars). Unique per span. |
| `parent_span_id` | `str \| None` | `span_id` of the parent span, or `None` for root. |

The `traceparent` W3C header format is:

```
00-<trace_id>-<span_id>-01
```

Use `tc.traceparent` (if generated) or construct it manually.

### A2A trace propagation

When Agent A calls Agent B as a tool, the trace context propagates
automatically:

1. `BeforeToolCallEvent` emitted on the tool's registry carries a *child*
   `TraceContext` (same `trace_id`, new `span_id`).
2. The tool's `execute()` method writes the child `TraceContext` into
   `permission_context.trace_context` **before** calling `_execute()`.
3. Agent B (the sub-agent) reads `permission_context.trace_context` when it
   emits its own events — so all B events share the same `trace_id`.

The net result: every event in a chain of agent → tool → sub-agent has the
same `trace_id`, with `parent_span_id` correctly wired.

---

## 5. Global registry and scope()

The **global registry** (`get_global_registry()`) is a process-wide singleton.
Every per-bot registry forwards its events to the global registry by default
(disable with `forward_to_global=False` in the YAML block or the
`EventEmitterMixin._init_events()` call).

Use the global registry when you want to observe ALL events from ALL bots in
one place — useful for centralized logging or metrics collection.

### Test isolation with scope()

Subscribing to the global registry in tests can contaminate other tests.
Use `scope()` to swap in a fresh registry for the duration of a block:

```python
from parrot.core.events.lifecycle import scope, BeforeInvokeEvent

def test_something():
    captured = []

    async def cb(e): captured.append(e)

    with scope() as registry:
        registry.subscribe(BeforeInvokeEvent, cb)
        # ... run the code under test
        # global registry is restored on exit — no contamination
```

`scope()` is a context manager and can be used in `pytest` fixtures or
inline.

---

## 6. Dispatch ordering

This is the most common source of surprises.

`Before*` events dispatch subscribers in **registration order** (first
registered, first called).

`After*` and `*Failed` events dispatch subscribers in **REVERSE registration
order** (last registered, first called).

```python
registry.subscribe(AfterInvokeEvent, close_db_handle)   # runs LAST
registry.subscribe(AfterInvokeEvent, flush_metrics)     # runs FIRST
```

The rationale is cleanup symmetry: resources acquired (or observed) in
registration order are released in the reverse order, mirroring how Python's
`try/finally` blocks unwind and how context-manager `__exit__` chains work.

If you registered three subscribers for `AfterInvokeEvent`:

```
Registration:  sub_A -> sub_B -> sub_C
Dispatch:      sub_C -> sub_B -> sub_A
```

This matches the behavior you would get if each subscriber were a nested
`async with` block: the innermost (last opened) is the first to exit.

---

## 7. Error isolation

AI-Parrot uses **model B** error isolation: subscriber exceptions are caught,
logged, and dispatched as a `SubscriberErrorEvent` to the global registry.
The original event continues dispatching to the remaining subscribers.

```python
async def bad_subscriber(evt):
    raise RuntimeError("oops")

async def good_subscriber(evt):
    print("I still run")

registry.subscribe(BeforeInvokeEvent, bad_subscriber)
registry.subscribe(BeforeInvokeEvent, good_subscriber)

await registry.emit(some_event)
# bad_subscriber raises → logged + SubscriberErrorEvent on global
# good_subscriber still fires
```

A subscriber that raises while handling a `SubscriberErrorEvent` is silently
dropped — no infinite error loops.

To observe subscriber errors, subscribe to `SubscriberErrorEvent` on the
global registry:

```python
from parrot.core.events.lifecycle import get_global_registry, SubscriberErrorEvent

async def on_sub_error(e: SubscriberErrorEvent) -> None:
    print(f"Subscriber {e.failed_subscriber!r} failed: {e.error_message}")

get_global_registry().subscribe(SubscriberErrorEvent, on_sub_error)
```

---

## 8. Dual-emit to EventBus

Each subscription can opt into forwarding the event to the project's
`EventBus` (the pre-existing message-bus infrastructure):

```python
registry.subscribe(
    AfterInvokeEvent,
    my_cb,
    forward_to_bus=True,
)
```

When `forward_to_bus=True` and the registry was constructed with an
`event_bus` reference, the event is also emitted on the bus with the channel
`"lifecycle.<EventClassName>"` and the payload from `event.to_dict()`.

**`ClientStreamChunkEvent` exception**: this event is explicitly blocked from
forwarding to `EventBus` regardless of the `forward_to_bus` flag, to prevent
flooding the bus during streaming responses. If you need stream-chunk
telemetry on the bus, aggregate chunks before emitting.

---

## 9. YAML declarative syntax

Agent YAML definitions can declare lifecycle subscribers inline, without
writing any Python wiring code:

```yaml
name: jira_specialist
llm: anthropic:claude-sonnet-4
prompt: |
  You are a Jira specialist.

events:
  # Optional: disable global forwarding for this bot (default: true)
  forward_to_global: true

  subscribers:
    # Form 1: single callback function + event filter
    - handler: parrot_tools.observability:log_tool_calls
      events: [BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent]
      where:
        tool_name: [jira_create_issue, jira_update_issue]
      forward_to_bus: false

    # Form 2: EventProvider class (bundles multiple callbacks)
    - provider: parrot.core.events.lifecycle.subscribers:OpenTelemetrySubscriber
      config:
        service_name: jira_specialist

    # Form 3: built-in subscriber with config
    - provider: parrot.core.events.lifecycle.subscribers:WebhookSubscriber
      config:
        url: ${EVENTS_WEBHOOK_URL}
        secret: ${EVENTS_WEBHOOK_SECRET}
```

Dotted paths use the format `module.path:ObjectName` (colon separator).
Unknown event class names or bad dotted paths raise `ValueError` /
`ImportError` at bot construction time with a clear message.

### EventProvider protocol

If you want to bundle multiple subscriptions, implement the `EventProvider`
protocol:

```python
from parrot.core.events.lifecycle import EventProvider, EventRegistry
from parrot.core.events.lifecycle import BeforeInvokeEvent, AfterInvokeEvent

class TelemetryProvider:
    def register(self, registry: EventRegistry) -> None:
        registry.subscribe(BeforeInvokeEvent, self.on_before)
        registry.subscribe(AfterInvokeEvent, self.on_after)

    async def on_before(self, e: BeforeInvokeEvent) -> None:
        print(f"start: {e.agent_name}")

    async def on_after(self, e: AfterInvokeEvent) -> None:
        print(f"end: {e.duration_ms:.1f} ms")
```

Then register it:

```python
bot.events.add_provider(TelemetryProvider())
```

---

## 10. Built-in subscribers

### LoggingSubscriber

Logs every event via `navconfig.logging` at a configurable level. Uses the
logger `"parrot.core.events.lifecycle"`.

```python
from parrot.core.events.lifecycle import LoggingSubscriber

bot.events.add_provider(LoggingSubscriber(level="DEBUG"))
```

### OpenTelemetrySubscriber

Maps lifecycle events to OpenTelemetry spans. Requires the `otel` extra:

```bash
uv add "ai-parrot[otel]"
# or
uv pip install "ai-parrot[otel]"
```

```python
from parrot.core.events.lifecycle import OpenTelemetrySubscriber
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

exporter = InMemorySpanExporter()
bot.events.add_provider(
    OpenTelemetrySubscriber(service_name="my_agent", exporter=exporter)
)
```

If `opentelemetry-api` and `opentelemetry-sdk` are not installed, importing
`OpenTelemetrySubscriber` raises an `ImportError` with a clear message
pointing to the `otel` extra.

### WebhookSubscriber

POSTs serialized events to an HTTPS endpoint asynchronously. Includes HMAC
request signing if a `secret` is configured.

```python
from parrot.core.events.lifecycle import WebhookSubscriber

bot.events.add_provider(
    WebhookSubscriber(
        url="https://hooks.example.com/parrot-events",
        secret="my-hmac-secret",   # optional; signs with HMAC-SHA256
        event_types=[AfterInvokeEvent, InvokeFailedEvent],
    )
)
```

---

## 11. emit_nowait gotcha

`emit_nowait(event)` is a synchronous helper for contexts where you cannot
`await`. It schedules an `asyncio.Task` using the **running** event loop.

```python
# Works — loop is running, task fires on next await
def sync_hook(self):
    self.events.emit_nowait(some_event)    # task scheduled
    # ... event fires before any subsequent await in the caller
```

**What can go wrong:**

```python
# Does NOT work — no running loop
loop = asyncio.get_event_loop()
registry.emit_nowait(some_event)   # raises RuntimeError or silently drops
```

In tests, use `await asyncio.sleep(0)` after synchronous code that calls
`emit_nowait` to drain the task queue before making assertions:

```python
async def test_tool_emits_before_event():
    tool = MyTool()
    tool.events.subscribe(BeforeToolCallEvent, captured.append)
    await tool.execute(pctx)
    await asyncio.sleep(0)   # drain emit_nowait tasks
    assert len(captured) == 1
```

---

## 12. Migration guide from `_trigger_event` / `add_event_listener`

The old string-keyed event system (`AbstractBot._trigger_event` /
`AbstractBot.add_event_listener`) is deprecated as of FEAT-176. It continues
to work and emits `DeprecationWarning`, but will be removed in Phase 3.

### Side-by-side comparison

| Before (legacy) | After (FEAT-176) |
|---|---|
| `bot.add_event_listener("status_changed", cb)` | `bot.events.subscribe(AgentStatusChangedEvent, cb)` |
| `cb(**kwargs)` — stringly-typed dict payload | `cb(event: AgentStatusChangedEvent)` — frozen, typed |
| No trace propagation | `event.trace_context.trace_id` for distributed correlation |
| Sync callbacks only | Async-only (`async def cb(event)`) |
| One global event namespace per bot | Per-bot registry + process-wide global registry |
| No filtering | `where=` predicate on each subscription |
| `_trigger_event("status_changed", old=..., new=...)` | `await self.events.emit(AgentStatusChangedEvent(...))` |

### Legacy bridge

The legacy `_trigger_event` call internally routes through the new pipeline
via a `_LegacyEventBridge` subscriber. Existing `add_event_listener`
subscribers continue to fire — they receive the same `**kwargs` as before.

To silence the deprecation warning, migrate your listeners:

```python
# Before
bot.add_event_listener("status_changed", lambda old, new, **kw: print(old, "->", new))

# After
async def on_status(e: AgentStatusChangedEvent) -> None:
    print(e.old_status, "->", e.new_status)

bot.events.subscribe(AgentStatusChangedEvent, on_status)
```

### Deprecation timeline

- **Phase 1 (FEAT-176)**: `_trigger_event` and `add_event_listener` emit
  `DeprecationWarning`, continue to work.
- **Phase 2**: Warning becomes an error under `PARROT_STRICT=1`.
- **Phase 3**: Legacy API removed entirely.

---

## 13. What is not here yet

- **Interceptors (Phase 2)**: subscribers that can modify or cancel an event
  before it propagates. Currently subscriptions are read-only.
- **Crew events (Phase 1.5)**: `AgentCrew`-level events (crew started, agent
  assigned, crew finished) are not emitted yet.
- **Cross-process EventBus forwarding**: the `forward_to_bus` flag writes to
  the in-process `EventBus`. Multi-process / networked forwarding is a
  separate effort.
- **Sphinx / MkDocs API reference autogeneration**: this document is
  hand-maintained. An autogenerated reference is planned.
