---
type: Wiki Overview
title: 'TASK-1186: Implement EventRegistry with dispatch and dual-emit'
id: doc:sdd-tasks-completed-task-1186-event-registry-dispatch-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Module 5 of the spec. `EventRegistry` is the heart of the dispatch pipeline:
  it stores subscriptions per scope, matches events by `isinstance`, runs callbacks
  in deterministic order (forward for Before*, reverse for After*/Failed), isolates
  subscriber exceptions via the model-B e'
relates_to:
- concept: mod:parrot.core.events.evb
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.base
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.events
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.global_registry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.meta
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.registry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.trace
  rel: mentions
---

# TASK-1186: Implement EventRegistry with dispatch and dual-emit

**Feature**: FEAT-176 — Lifecycle Events System
**Spec**: `sdd/specs/FEAT-176-lifecycle-events-system.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-1184
**Assigned-to**: unassigned

---

## Context

Module 5 of the spec. `EventRegistry` is the heart of the dispatch pipeline: it stores subscriptions per scope, matches events by `isinstance`, runs callbacks in deterministic order (forward for Before*, reverse for After*/Failed), isolates subscriber exceptions via the model-B error model (emit a `SubscriberErrorEvent` to the global registry, never break the agent flow), and optionally dual-emits to `EventBus`.

Spec section: §2 New Public Interfaces (lines 354–411) and §3 Module 5. Spec dispatch rules are at §2 lines 367–378.

---

## Scope

- Implement `EventRegistry` per the spec public interface (lines 354–411).
- Implement isinstance-based dispatch matching subclass subscriptions (e.g., subscribing to `LifecycleEvent` receives everything).
- Implement reverse ordering for any event class whose name starts with `After` or ends with `Failed`.
- Implement per-subscriber `forward_to_bus` opt-in dual-emit to `EventBus`. Bus channel: `f"{bus_channel_prefix}.{type(event).__name__}"` (default prefix: `"lifecycle"`).
- Implement subscriber error isolation: catch every exception inside `emit()`, log it via `navconfig.logging`, and emit a `SubscriberErrorEvent` to the global registry (the global registry import is forward-referenced and lazily resolved — see Notes).
- Implement `subscribe()`, `unsubscribe()`, `add_provider()`, `emit()`, and the sync helper `emit_nowait()` (Q9 resolution: see §8 of the spec).
- Tests: subscriber receives matching events only; subclass subscription captures all; reverse order for After*/Failed; where-filter; subscriber exception isolated; SubscriberErrorEvent emitted to global; recursion guard prevents infinite SubscriberErrorEvent loop; dual-emit opt-in honored; `ClientStreamChunkEvent` never auto-forwards.

**NOT in scope**: global singleton + `scope()` (TASK-1187), `EventProvider` Protocol (TASK-1188), `EventEmitterMixin` (TASK-1189), built-in subscribers, YAML loading.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/lifecycle/registry.py` | CREATE | `EventRegistry` + `AsyncSubscriber` type alias. |
| `packages/ai-parrot/tests/unit/events/lifecycle/test_registry.py` | CREATE | Dispatch, ordering, error isolation, dual-emit tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio
import logging
import traceback
import uuid
from typing import Awaitable, Callable, Optional, Type, TypeVar

from parrot.core.events.lifecycle.base import LifecycleEvent       # TASK-1183
from parrot.core.events.lifecycle.meta import SubscriberErrorEvent  # TASK-1184
from parrot.core.events.evb import EventBus                         # existing
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/core/events/evb.py — VERIFIED
class EventBus:
    async def emit(
        self,
        event_type: str,           # hierarchical dotted string
        payload: dict[str, Any],   # JSON-serializable dict
        **kwargs,
    ) -> int: ...   # returns count of handlers that processed the event
```

`EventBus.emit` is async and returns int. `EventBus` may be `None` (registry constructed without bus).

```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/base.py — from TASK-1183
@dataclass(frozen=True)
class LifecycleEvent(ABC):
    trace_context: TraceContext
    event_id: str
    timestamp: datetime
    source_type: str
    source_name: str
    def to_dict(self) -> dict[str, Any]: ...
```

```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/meta.py — from TASK-1184
@dataclass(frozen=True)
class SubscriberErrorEvent(LifecycleEvent):
    failed_subscriber: str = ""
    original_event_class: str = ""
    error_type: str = ""
    error_message: str = ""
    traceback: str = ""
```

### Does NOT Exist

- ~~`EventRegistry` elsewhere in codebase~~ — being created now.
- ~~`EventBus.lifecycle_emit`~~ — use plain `EventBus.emit(channel, payload)`.
- ~~`asyncio.run_coroutine_threadsafe` for this task~~ — async-only API; sync helper is TASK-1189's `emit_nowait`.

---

## Implementation Notes

### Public API shape

```python
AsyncSubscriber = Callable[[LifecycleEvent], Awaitable[None]]
E = TypeVar("E", bound=LifecycleEvent)


class EventRegistry:
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
    ) -> str: ...

    def unsubscribe(self, subscription_id: str) -> bool: ...

    def add_provider(self, provider: "EventProvider") -> list[str]:
        # NB: EventProvider lives in TASK-1188; import lazily inside the method
        # to avoid a circular dependency at module load time.
        ...

    async def emit(self, event: LifecycleEvent) -> None:
        # Never raises — isolation per model B.
        ...
```

### Subscription storage

Use a list of `Subscription` records (or a plain `@dataclass`) keyed by `subscription_id` (`str(uuid.uuid4())`). Each subscription carries `event_type`, `callback`, `where`, `forward_to_bus`, `order` (for stable sort).

### Dispatch algorithm

```python
async def emit(self, event: LifecycleEvent) -> None:
    matching = [
        s for s in self._subscriptions
        if isinstance(event, s.event_type)
        and (s.where is None or s.where(event))
    ]
    # Reverse for cleanup-symmetry events
    cls_name = type(event).__name__
    if cls_name.startswith("After") or cls_name.endswith("Failed"):
        matching.reverse()
    for sub in matching:
        try:
            await sub.callback(event)
        except Exception as exc:
            self.logger.exception(
                "Lifecycle subscriber %s raised on %s", sub.callback, cls_name,
            )
            self._emit_subscriber_error(event, sub, exc)
        # Per-subscriber dual-emit
        if sub.forward_to_bus and self._event_bus is not None:
            channel = f"{self._bus_channel_prefix}.{cls_name}"
            try:
                await self._event_bus.emit(channel, event.to_dict())
            except Exception:
                self.logger.exception("Dual-emit to bus failed for %s", channel)
    # Forward to global registry if enabled
    if self._forward_to_global:
        self._forward_to_global_safely(event)
```

### Recursion guard (no infinite SubscriberErrorEvent loops)

When emitting a `SubscriberErrorEvent` because a subscriber failed, do NOT re-route that meta-event back through subscribers that listen to `SubscriberErrorEvent` and ALSO raise. Track recursion via a `contextvars.ContextVar[bool]` named `_emitting_meta` (set to True during meta-emit, checked at the top of `emit` — if True and event is `SubscriberErrorEvent` from a failing subscriber, log and drop).

### Forward-to-global lazy import

```python
def _forward_to_global_safely(self, event: LifecycleEvent) -> None:
    # Lazy import avoids circularity: global_registry depends on EventRegistry.
    from parrot.core.events.lifecycle.global_registry import get_global_registry
    global_reg = get_global_registry()
    if global_reg is self:
        return   # don't re-emit to self
    # Fire-and-forget — the forwarded emit must NOT block the source emit.
    asyncio.create_task(
        global_reg.emit(event),
        name=f"lifecycle.forward.{type(event).__name__}",
    )
```

If `get_global_registry()` raises (e.g., test isolation issue), log and continue — never break the source emit.

### Building `SubscriberErrorEvent`

```python
def _emit_subscriber_error(self, original_event, sub, exc) -> None:
    err_evt = SubscriberErrorEvent(
        trace_context=original_event.trace_context,
        failed_subscriber=repr(sub.callback),
        original_event_class=type(original_event).__name__,
        error_type=type(exc).__name__,
        error_message=str(exc),
        traceback=traceback.format_exc(),
    )
    # Schedule on the global registry, guarded by recursion ctxvar
    from parrot.core.events.lifecycle.global_registry import get_global_registry
    asyncio.create_task(
        get_global_registry()._emit_meta(err_evt),
        name=f"lifecycle.meta.{type(original_event).__name__}",
    )
```

The global registry exposes an internal `_emit_meta(evt)` method that sets the recursion ctxvar before dispatching — this is added in TASK-1187 (`EventRegistry` itself should expose a `_emit_meta` method that does the ctxvar dance). Implement the ctxvar logic on `EventRegistry` here so TASK-1187 only needs to wire up the singleton.

### Key Constraints

- `emit()` is async and MUST NEVER raise.
- All subscriber callbacks are async (`Callable[[E], Awaitable[None]]`).
- Use `navconfig.logging` (`logger = logging.getLogger("parrot.core.events.lifecycle.registry")`).
- Short-circuit when there are zero matching subscriptions to avoid `to_dict()` cost on hot paths (especially relevant for `ClientStreamChunkEvent` — see TASK-1194).

### `ClientStreamChunkEvent` no-auto-forward rule

The spec says: "ClientStreamChunkEvent NEVER dual-emits to EventBus unless the subscriber explicitly opts in via forward_to_bus=True."

The dispatch loop already honors `forward_to_bus` per subscriber. The acceptance test `test_stream_chunk_event_no_bus_pressure` verifies that a registry with stream-chunk subscribers but `forward_to_bus=False` produces zero `EventBus.emit` calls.

Nothing special is needed in the dispatcher beyond honoring the flag. Add a documented note in the docstring so future implementers don't add a global override.

---

## Acceptance Criteria

- [ ] `EventRegistry` implemented per spec public interface.
- [ ] `subscribe()` returns a unique subscription_id; `unsubscribe(id)` removes the subscription and returns True (False if id unknown).
- [ ] Subscribing to `LifecycleEvent` (parent) receives every concrete event.
- [ ] Subscribing to `BeforeToolCallEvent` does NOT receive `AfterToolCallEvent`.
- [ ] `After*` and `*Failed` events run subscribers in REVERSE registration order.
- [ ] `Before*` events run in FORWARD order.
- [ ] `where=lambda e: e.tool_name == "x"` filter is honored.
- [ ] Subscriber raising does NOT propagate; emit returns normally.
- [ ] A `SubscriberErrorEvent` is scheduled to the global registry after a subscriber failure.
- [ ] Recursion guard prevents infinite SubscriberErrorEvent loops.
- [ ] `forward_to_bus=False` → zero `EventBus.emit` calls; `forward_to_bus=True` → exactly one.
- [ ] 1000 `ClientStreamChunkEvent`s with stream-chunk subscriber but no `forward_to_bus` → zero bus calls.
- [ ] Unit tests pass: `pytest packages/ai-parrot/tests/unit/events/lifecycle/test_registry.py -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/core/events/lifecycle/registry.py` is clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/events/lifecycle/test_registry.py
import asyncio
import pytest
from unittest.mock import AsyncMock

from parrot.core.events.evb import EventBus
from parrot.core.events.lifecycle.registry import EventRegistry
from parrot.core.events.lifecycle.trace import TraceContext
from parrot.core.events.lifecycle.events import (
    BeforeInvokeEvent, AfterInvokeEvent, InvokeFailedEvent,
    BeforeToolCallEvent, AfterToolCallEvent,
    ClientStreamChunkEvent,
)
from parrot.core.events.lifecycle.base import LifecycleEvent


@pytest.fixture
def registry():
    return EventRegistry(forward_to_global=False)


@pytest.fixture
def trace_root():
    return TraceContext.new_root()


class TestEventRegistryDispatch:
    @pytest.mark.asyncio
    async def test_isinstance_match(self, registry, trace_root):
        received = []
        registry.subscribe(BeforeInvokeEvent, lambda e: received.append(e) or asyncio.sleep(0))
        await registry.emit(BeforeInvokeEvent(trace_context=trace_root))
        await registry.emit(AfterInvokeEvent(trace_context=trace_root))
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_subclass_subscription(self, registry, trace_root):
        received = []
        async def cb(e): received.append(e)
        registry.subscribe(LifecycleEvent, cb)
        await registry.emit(BeforeInvokeEvent(trace_context=trace_root))
        await registry.emit(AfterInvokeEvent(trace_context=trace_root))
        assert len(received) == 2

    @pytest.mark.asyncio
    async def test_reverse_order_after_event(self, registry, trace_root):
        order = []
        async def a(e): order.append("a")
        async def b(e): order.append("b")
        registry.subscribe(AfterInvokeEvent, a)
        registry.subscribe(AfterInvokeEvent, b)
        await registry.emit(AfterInvokeEvent(trace_context=trace_root))
        assert order == ["b", "a"]

    @pytest.mark.asyncio
    async def test_normal_order_before_event(self, registry, trace_root):
        order = []
        async def a(e): order.append("a")
        async def b(e): order.append("b")
        registry.subscribe(BeforeInvokeEvent, a)
        registry.subscribe(BeforeInvokeEvent, b)
        await registry.emit(BeforeInvokeEvent(trace_context=trace_root))
        assert order == ["a", "b"]

    @pytest.mark.asyncio
    async def test_reverse_order_failed_event(self, registry, trace_root):
        order = []
        async def a(e): order.append("a")
        async def b(e): order.append("b")
        registry.subscribe(InvokeFailedEvent, a)
        registry.subscribe(InvokeFailedEvent, b)
        await registry.emit(InvokeFailedEvent(trace_context=trace_root))
        assert order == ["b", "a"]

    @pytest.mark.asyncio
    async def test_where_filter(self, registry, trace_root):
        received = []
        async def cb(e): received.append(e)
        registry.subscribe(
            BeforeToolCallEvent, cb,
            where=lambda e: e.tool_name == "keep",
        )
        await registry.emit(BeforeToolCallEvent(trace_context=trace_root, tool_name="drop"))
        await registry.emit(BeforeToolCallEvent(trace_context=trace_root, tool_name="keep"))
        assert [e.tool_name for e in received] == ["keep"]

    @pytest.mark.asyncio
    async def test_subscriber_exception_isolated(self, registry, trace_root):
        survived = []
        async def boom(e): raise RuntimeError("boom")
        async def survivor(e): survived.append(e)
        registry.subscribe(BeforeInvokeEvent, boom)
        registry.subscribe(BeforeInvokeEvent, survivor)
        await registry.emit(BeforeInvokeEvent(trace_context=trace_root))
        assert len(survived) == 1

    @pytest.mark.asyncio
    async def test_dual_emit_opt_in(self, trace_root):
        bus = EventBus(use_redis=False)
        bus.emit = AsyncMock()
        reg = EventRegistry(event_bus=bus, forward_to_global=False)
        async def cb(e): pass
        reg.subscribe(BeforeInvokeEvent, cb, forward_to_bus=False)
        await reg.emit(BeforeInvokeEvent(trace_context=trace_root))
        assert bus.emit.call_count == 0

        reg.subscribe(BeforeInvokeEvent, cb, forward_to_bus=True)
        await reg.emit(BeforeInvokeEvent(trace_context=trace_root))
        assert bus.emit.call_count == 1

    @pytest.mark.asyncio
    async def test_stream_chunk_no_auto_forward(self, trace_root):
        bus = EventBus(use_redis=False)
        bus.emit = AsyncMock()
        reg = EventRegistry(event_bus=bus, forward_to_global=False)
        async def cb(e): pass
        reg.subscribe(ClientStreamChunkEvent, cb, forward_to_bus=False)
        for i in range(1000):
            await reg.emit(ClientStreamChunkEvent(trace_context=trace_root, chunk_index=i))
        assert bus.emit.call_count == 0
```

---

## Agent Instructions

1. Read spec §2 (Public Interfaces, lines 354–411) and §3 Module 5.
2. Confirm TASK-1184 is in `sdd/tasks/completed/` and that `SubscriberErrorEvent` is importable.
3. Implement the registry with the architecture above; keep the public API exactly as the spec lists.
4. Note: tests for `SubscriberErrorEvent` propagation to the global registry are easier after TASK-1187 lands. For this task, verify only that a meta-event is *scheduled* (e.g., via a mock of `get_global_registry`).
5. Update the per-spec index, move this file to `sdd/tasks/completed/`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-15
**Notes**: EventRegistry implemented with isinstance dispatch, forward/reverse ordering (Before*=forward, After*/contain-Failed=reverse), per-subscriber forward_to_bus dual-emit, model-B error isolation, SubscriberErrorEvent scheduling, recursion guard via contextvars.ContextVar, and lazy global_registry import. 19/19 tests pass. Ruff clean. Deviation: reversed ordering check uses `"Failed" in cls_name` (not `endswith("Failed")`) because concrete event classes end with "Event" (e.g., "InvokeFailedEvent").

**Deviations from spec**: `"Failed" in cls_name` used instead of `cls_name.endswith("Failed")` to handle class names like `InvokeFailedEvent` that embed "Failed" but end with "Event".
