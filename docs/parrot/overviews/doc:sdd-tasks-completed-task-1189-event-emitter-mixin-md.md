---
type: Wiki Overview
title: 'TASK-1189: Implement EventEmitterMixin and emit_nowait helper'
id: doc:sdd-tasks-completed-task-1189-event-emitter-mixin-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Module 8 of the spec. `EventEmitterMixin` is the uniform interface attached
  to `AbstractBot`, `AbstractClient`, and `AbstractTool`. It exposes `self.events:
  EventRegistry` (lazily created) and wires the per-instance registry to the global
  registry (unless opted out). This task al'
relates_to:
- concept: mod:parrot.core.events.evb
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.events
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.global_registry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.mixin
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.registry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.trace
  rel: mentions
---

# TASK-1189: Implement EventEmitterMixin and emit_nowait helper

**Feature**: FEAT-176 — Lifecycle Events System
**Spec**: `sdd/specs/FEAT-176-lifecycle-events-system.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-1186, TASK-1187
**Assigned-to**: unassigned

---

## Context

Module 8 of the spec. `EventEmitterMixin` is the uniform interface attached to `AbstractBot`, `AbstractClient`, and `AbstractTool`. It exposes `self.events: EventRegistry` (lazily created) and wires the per-instance registry to the global registry (unless opted out). This task also implements `EventRegistry.emit_nowait()` — the sync-friendly helper that resolves spec open question Q9 for callers like `AbstractBot.status.setter` that cannot become async.

Spec section: §2 New Public Interfaces (lines 452–471), §3 Module 8, §8 Q9 (resolved).

---

## Scope

- Implement `EventEmitterMixin` per the spec public interface.
- Add `_init_events()` so subclasses call it from their `__init__`. The mixin does NOT call `super().__init__()` itself — subclasses are responsible for ordering.
- Expose `self.events` as a property; lazy-create the registry on first access (in case `_init_events` was never called — falls back to a safe default registry).
- Add `emit_nowait(event)` to `EventRegistry` (cross-cutting change to TASK-1186 deliverable): tries `asyncio.get_running_loop()`, schedules `create_task(self.emit(event), name=...)` if a loop is running, else logs at DEBUG and drops.
- Add unit tests covering: lazy registry creation, global forwarding default on, opt-out, emit_nowait under running loop, emit_nowait under no loop (silent drop).

**NOT in scope**: actual integration into `AbstractBot` / `AbstractClient` / `AbstractTool` (TASK-1193, TASK-1194, TASK-1195).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/lifecycle/mixin.py` | CREATE | `EventEmitterMixin`. |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/registry.py` | MODIFY | Add `emit_nowait(event)` method. |
| `packages/ai-parrot/tests/unit/events/lifecycle/test_mixin.py` | CREATE | Mixin + emit_nowait tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio
import logging
from typing import Optional

from parrot.core.events.evb import EventBus                          # existing
from parrot.core.events.lifecycle.registry import EventRegistry      # TASK-1186
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/registry.py — from TASK-1186
class EventRegistry:
    def __init__(
        self,
        *,
        event_bus: Optional[EventBus] = None,
        bus_channel_prefix: str = "lifecycle",
        forward_to_global: bool = True,
    ) -> None: ...
    async def emit(self, event: LifecycleEvent) -> None: ...

# global_registry — from TASK-1187
def get_global_registry() -> EventRegistry: ...
```

### Does NOT Exist

- ~~`AbstractBot.events` property~~ — being added (this mixin is what adds it once mixed in).
- ~~`emit_sync` public API~~ — the spec explicitly says NO sync emit API; use `emit_nowait`.
- ~~`asyncio.ensure_future(self.events.emit(...))` without a name~~ — every scheduled task MUST be named for debuggability.

---

## Implementation Notes

### Mixin shape

```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/mixin.py
from typing import Optional

from parrot.core.events.evb import EventBus
from parrot.core.events.lifecycle.registry import EventRegistry


class EventEmitterMixin:
    """Mixin providing a uniform ``self.events`` interface.

    Subclasses MUST call ``self._init_events()`` from their __init__,
    AFTER super().__init__() and before any emit. The mixin does not
    call super itself to avoid disturbing the host class's MRO.
    """

    _events_registry: Optional[EventRegistry]

    def _init_events(
        self,
        *,
        event_bus: Optional[EventBus] = None,
        forward_to_global: bool = True,
    ) -> None:
        self._events_registry = EventRegistry(
            event_bus=event_bus,
            forward_to_global=forward_to_global,
        )

    @property
    def events(self) -> EventRegistry:
        reg = getattr(self, "_events_registry", None)
        if reg is None:
            # Defensive fallback: caller forgot to invoke _init_events.
            self._events_registry = EventRegistry(forward_to_global=True)
            reg = self._events_registry
        return reg
```

### `emit_nowait` on `EventRegistry`

Add this method to `EventRegistry` (modify TASK-1186's file):

```python
def emit_nowait(self, event: LifecycleEvent) -> None:
    """Schedule emit() on the running event loop, or drop with DEBUG log.

    Use this from sync contexts (e.g., property setters) where you cannot
    await. The event is NOT guaranteed to be processed if no loop is
    running at call time — this is acceptable for observability events.

    Resolution of spec open question Q9.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        self.logger.debug(
            "emit_nowait dropped %s: no running event loop",
            type(event).__name__,
        )
        return
    loop.create_task(
        self.emit(event),
        name=f"lifecycle.{type(event).__name__}",
    )
```

### Lazy-init defensive fallback

If a host class uses `self.events` without ever calling `_init_events()`, the property falls back to a default registry. This prevents `AttributeError` surprises during early refactors. The fallback registry forwards to global so observability still works.

### Key Constraints

- The mixin must NOT call `super().__init__()` — host classes have varying base hierarchies.
- `self.events` must be a property, not a plain attribute — keeps the lazy fallback path clean.
- `emit_nowait` must NEVER raise.
- Use `logger = logging.getLogger("parrot.core.events.lifecycle.mixin")`.

---

## Acceptance Criteria

- [ ] `EventEmitterMixin` defined in `mixin.py`.
- [ ] `from parrot.core.events.lifecycle.mixin import EventEmitterMixin` works.
- [ ] A class that inherits the mixin and calls `_init_events()` has `self.events` as an `EventRegistry`.
- [ ] A class that inherits the mixin but never calls `_init_events()` still has `self.events` (lazy fallback).
- [ ] `forward_to_global=True` (default) → emitting on `self.events` reaches the global registry.
- [ ] `forward_to_global=False` → emitting does NOT reach the global registry.
- [ ] `emit_nowait(evt)` under a running asyncio loop creates a named task.
- [ ] `emit_nowait(evt)` outside a running loop logs at DEBUG and returns without raising.
- [ ] Unit tests pass: `pytest packages/ai-parrot/tests/unit/events/lifecycle/test_mixin.py -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/core/events/lifecycle/mixin.py packages/ai-parrot/src/parrot/core/events/lifecycle/registry.py` is clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/events/lifecycle/test_mixin.py
import asyncio
import logging
import pytest

from parrot.core.events.lifecycle.mixin import EventEmitterMixin
from parrot.core.events.lifecycle.registry import EventRegistry
from parrot.core.events.lifecycle.global_registry import scope
from parrot.core.events.lifecycle.events import BeforeInvokeEvent
from parrot.core.events.lifecycle.trace import TraceContext


class _Host(EventEmitterMixin):
    def __init__(self, **kw):
        self._init_events(**kw)


class TestMixin:
    def test_init_creates_registry(self):
        h = _Host()
        assert isinstance(h.events, EventRegistry)

    def test_lazy_fallback(self):
        class _NoInit(EventEmitterMixin):
            pass
        h = _NoInit()
        assert isinstance(h.events, EventRegistry)

    @pytest.mark.asyncio
    async def test_global_forwarding_default(self):
        captured = []
        async def cap(e): captured.append(e)
        with scope() as global_reg:
            global_reg.subscribe(BeforeInvokeEvent, cap)
            h = _Host()
            await h.events.emit(BeforeInvokeEvent(trace_context=TraceContext.new_root()))
            # Forwarding is via create_task — wait for the loop to drain.
            await asyncio.sleep(0)
        assert len(captured) == 1

    @pytest.mark.asyncio
    async def test_global_forwarding_disabled(self):
        captured = []
        async def cap(e): captured.append(e)
        with scope() as global_reg:
            global_reg.subscribe(BeforeInvokeEvent, cap)
            h = _Host(forward_to_global=False)
            await h.events.emit(BeforeInvokeEvent(trace_context=TraceContext.new_root()))
            await asyncio.sleep(0)
        assert len(captured) == 0

    @pytest.mark.asyncio
    async def test_emit_nowait_under_loop(self):
        captured = []
        async def cap(e): captured.append(e)
        reg = EventRegistry(forward_to_global=False)
        reg.subscribe(BeforeInvokeEvent, cap)
        reg.emit_nowait(BeforeInvokeEvent(trace_context=TraceContext.new_root()))
        await asyncio.sleep(0)   # let the task run
        assert len(captured) == 1

    def test_emit_nowait_no_loop_drops(self, caplog):
        reg = EventRegistry(forward_to_global=False)
        with caplog.at_level(logging.DEBUG, logger="parrot.core.events.lifecycle.registry"):
            reg.emit_nowait(BeforeInvokeEvent(trace_context=TraceContext.new_root()))
        assert any("no running event loop" in r.message for r in caplog.records)
```

---

## Agent Instructions

1. Read spec §2 lines 452–471 and §3 Module 8.
2. Confirm TASK-1186 and TASK-1187 are in `sdd/tasks/completed/`.
3. Implement, run tests, update the per-spec index, move this file to `sdd/tasks/completed/`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-15
**Notes**: EventEmitterMixin implemented with lazy fallback, forward_to_global default. emit_nowait added to EventRegistry using asyncio.get_running_loop(). 11/11 tests pass. Ruff clean.

**Deviations from spec**: none
