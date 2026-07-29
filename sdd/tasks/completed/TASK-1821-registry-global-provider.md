# TASK-1821: Move registry, global_registry, and provider

**Feature**: FEAT-313 — EventBus Lifecycle Extraction (navigator-eventbus phase 2)
**Spec**: `sdd/specs/eventbus-lifecycle-extraction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1820
**Assigned-to**: unassigned

---

## Context

This is Module 2. It moves the event dispatch engine — `EventRegistry`,
`get_global_registry()`, `scope()`, `EventProvider` — from ai-parrot into
the package. The registry is the largest single module (447 LOC) and contains
the dual-emit path to `EventBus`, model B error isolation, the recursion
guard, and the `_Subscription` dataclass.

One targeted change: the `TYPE_CHECKING` import of `EventBus` switches from
`parrot.core.events.evb` to `navigator_eventbus.evb` (the phase-1 facade).

---

## Scope

- Copy `registry.py` (447 LOC) changing:
  - `from parrot.core.events.lifecycle.base import LifecycleEvent` → `from navigator_eventbus.lifecycle.base import LifecycleEvent`
  - `from parrot.core.events.lifecycle.meta import SubscriberErrorEvent` → `from navigator_eventbus.lifecycle.meta import SubscriberErrorEvent`
  - `TYPE_CHECKING: from parrot.core.events.evb import EventBus` → `from navigator_eventbus.evb import EventBus`
  - Lazy in-method imports of `provider` and `global_registry` → update paths to `navigator_eventbus.lifecycle.*`
- Copy `global_registry.py` (91 LOC) changing:
  - `from parrot.core.events.lifecycle.registry import EventRegistry` → `from navigator_eventbus.lifecycle.registry import EventRegistry`
- Copy `provider.py` (51 LOC) changing:
  - `TYPE_CHECKING: from parrot.core.events.lifecycle.registry import EventRegistry` → `from navigator_eventbus.lifecycle.registry import EventRegistry`
- Preserve lazy in-method imports in `registry.py` (:218, :354, :432) — they break import cycles.
- Write unit tests for registry (emit never raises, dual-emit fire-and-forget), global_registry (scope isolation), provider protocol.

**NOT in scope**: mixin, yaml_loader, subscribers, public API __init__.py.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/navigator_eventbus/lifecycle/registry.py` | CREATE | EventRegistry, AsyncSubscriber, _Subscription (447 LOC) |
| `src/navigator_eventbus/lifecycle/global_registry.py` | CREATE | get_global_registry(), scope() (91 LOC) |
| `src/navigator_eventbus/lifecycle/provider.py` | CREATE | EventProvider protocol (51 LOC) |
| `tests/lifecycle/test_registry.py` | CREATE | EventRegistry unit tests |
| `tests/lifecycle/test_registry_fire_and_forget.py` | CREATE | Dual-emit bus integration |
| `tests/lifecycle/test_global_registry.py` | CREATE | Scope isolation tests |
| `tests/lifecycle/test_provider.py` | CREATE | EventProvider protocol tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# registry.py imports (packages/ai-parrot/src/parrot/core/events/lifecycle/registry.py)
from __future__ import annotations                           # :5
import asyncio                                               # :7
import logging                                               # :8
import traceback as tb_mod                                   # :9
from collections import defaultdict                          # :10
from dataclasses import dataclass, field                     # :11
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional, Type, TypeVar  # :34
from parrot.core.events.lifecycle.base import LifecycleEvent       # :36 → CHANGE
from parrot.core.events.lifecycle.meta import SubscriberErrorEvent # :37 → CHANGE
if TYPE_CHECKING:
    from parrot.core.events.evb import EventBus                    # :40 → CHANGE to navigator_eventbus.evb

# Lazy in-method imports inside registry.py (MUST remain lazy):
# :218  from parrot.core.events.lifecycle.provider import EventProvider → CHANGE
# :354  from parrot.core.events.lifecycle.global_registry import get_global_registry → CHANGE
# :432  from parrot.core.events.lifecycle.global_registry import get_global_registry → CHANGE

# global_registry.py imports
from parrot.core.events.lifecycle.registry import EventRegistry  # :25 → CHANGE

# provider.py imports
if TYPE_CHECKING:
    from parrot.core.events.lifecycle.registry import EventRegistry  # :16 → CHANGE
```

### Existing Signatures to Use

```python
# registry.py:64
@dataclass
class _Subscription:
    callback: Callable
    event_type: type
    where: Optional[Callable[[Any], bool]]
    subscription_id: str
    forward_to_bus: bool = False

# registry.py:90
class EventRegistry:
    def __init__(self, *, event_bus: "Optional[EventBus]" = None,
                 bus_channel_prefix: str = "lifecycle",
                 forward_to_global: bool = True) -> None:    # :104
    def subscribe(self, event_type, callback, *, where=None,
                  forward_to_bus=False) -> str:               # :121
    def unsubscribe(self, subscription_id: str) -> bool:      # :159
    async def emit(self, event: LifecycleEvent) -> None:      # :235 — NEVER raises
    def emit_nowait(self, event: LifecycleEvent) -> None:     # :366

# global_registry.py:37
def get_global_registry() -> EventRegistry: ...
# global_registry.py:59
def scope() -> Iterator[EventRegistry]: ...    # contextmanager

# provider.py:20
@runtime_checkable
class EventProvider(Protocol):
    def register(self, registry: "EventRegistry") -> None: ...  # :45

# Phase-1 facade (navigator_eventbus.evb — verified in FEAT-312):
class EventBus:
    async def emit(self, event_type: str, payload: dict, **kwargs) -> int  # duck-typed
```

### Does NOT Exist

- ~~Runtime import of `EventBus` in `registry.py`~~ — TYPE_CHECKING only (:40); dual-emit is duck-typed `bus.emit(channel, dict)`.
- ~~`navigator_eventbus.lifecycle.registry` today~~ — does not exist; this task creates it.
- ~~`EventRegistry.close()` or shutdown method~~ — no such method; the registry is never closed.
- ~~Direct import of `global_registry` at module level in registry.py~~ — it's lazy (in-method) to avoid import cycles.

---

## Implementation Notes

### Key Constraints
- Lazy in-method imports in `registry.py` (:218, :354, :432) MUST remain lazy — they break import cycles between registry/provider/global_registry.
- Model B error isolation: `emit()` NEVER propagates subscriber exceptions. On failure, a `SubscriberErrorEvent` is emitted with a recursion guard (checked at registry.py ~:260-270).
- Dual-emit to EventBus is fire-and-forget via `asyncio.create_task()` — the emitter never waits.
- `scope()` uses `contextvars.ContextVar` — tests must use `scope()` for isolation.
- The logger name should change from `parrot.core.events.lifecycle.registry` to `navigator_eventbus.lifecycle.registry`.

### References in Codebase
- `packages/ai-parrot/src/parrot/core/events/lifecycle/registry.py` — copy source (447 LOC)
- `packages/ai-parrot/src/parrot/core/events/lifecycle/global_registry.py` — copy source (91 LOC)
- `packages/ai-parrot/src/parrot/core/events/lifecycle/provider.py` — copy source (51 LOC)
- `src/navigator_eventbus/evb.py` — phase-1 facade, TYPE_CHECKING target

---

## Acceptance Criteria

- [ ] `from navigator_eventbus.lifecycle.registry import EventRegistry, AsyncSubscriber` works
- [ ] `from navigator_eventbus.lifecycle.global_registry import get_global_registry, scope` works
- [ ] `from navigator_eventbus.lifecycle.provider import EventProvider` works
- [ ] No `parrot.*` imports: `grep -r "from parrot\|import parrot" src/navigator_eventbus/lifecycle/{registry,global_registry,provider}.py` → 0 hits
- [ ] `EventRegistry.__init__(*, event_bus=None, bus_channel_prefix="lifecycle", forward_to_global=True)` signature preserved
- [ ] `subscribe(event_type, callback, *, where=None, forward_to_bus=False)` returns subscription ID
- [ ] `emit()` never raises — failing subscriber isolated via SubscriberErrorEvent
- [ ] `emit_nowait()` enqueues via `asyncio.create_task`
- [ ] `scope()` isolates the global registry per-context
- [ ] `EventProvider` is `@runtime_checkable`
- [ ] All tests pass: `pytest tests/lifecycle/test_registry*.py tests/lifecycle/test_global_registry.py tests/lifecycle/test_provider.py -v`
- [ ] No linting errors: `ruff check src/navigator_eventbus/lifecycle/`

---

## Test Specification

```python
# tests/lifecycle/test_registry.py
import pytest
from navigator_eventbus.lifecycle.registry import EventRegistry
from navigator_eventbus.lifecycle.base import LifecycleEvent
from navigator_eventbus.lifecycle.trace import TraceContext
from navigator_eventbus.lifecycle.meta import SubscriberErrorEvent
from dataclasses import dataclass

@dataclass(frozen=True)
class _TestEvent(LifecycleEvent):
    detail: str = ""

@pytest.fixture
def registry():
    return EventRegistry(forward_to_global=False)

class TestEventRegistry:
    @pytest.mark.asyncio
    async def test_emit_calls_subscriber(self, registry):
        received = []
        registry.subscribe(_TestEvent, lambda e: received.append(e))
        evt = _TestEvent(trace_context=TraceContext.new_root(),
                         source_type="test", source_name="unit")
        await registry.emit(evt)
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_emit_never_raises_on_subscriber_error(self, registry):
        def bad_handler(e):
            raise RuntimeError("boom")
        registry.subscribe(_TestEvent, bad_handler)
        evt = _TestEvent(trace_context=TraceContext.new_root(),
                         source_type="test", source_name="unit")
        await registry.emit(evt)  # must not raise

    @pytest.mark.asyncio
    async def test_subscriber_error_emits_meta_event(self, registry):
        errors = []
        def bad_handler(e):
            raise RuntimeError("boom")
        registry.subscribe(_TestEvent, bad_handler)
        registry.subscribe(SubscriberErrorEvent, lambda e: errors.append(e))
        evt = _TestEvent(trace_context=TraceContext.new_root(),
                         source_type="test", source_name="unit")
        await registry.emit(evt)
        assert len(errors) == 1
        assert "boom" in errors[0].error_message

# tests/lifecycle/test_global_registry.py
from navigator_eventbus.lifecycle.global_registry import get_global_registry, scope

class TestGlobalRegistry:
    def test_scope_isolation(self):
        with scope() as reg1:
            with scope() as reg2:
                assert reg1 is not reg2
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/eventbus-lifecycle-extraction.spec.md` §2 Module 2
2. **Check dependencies** — verify TASK-1820 is done (base/trace/meta exist)
3. **Verify the Codebase Contract** — confirm source signatures still match
4. **Work in the navigator-eventbus repo** at `/home/jesuslara/proyectos/navigator-eventbus`
5. **Copy files**, changing only import paths (parrot → navigator_eventbus)
6. **Preserve lazy imports** in registry.py — do NOT make them module-level
7. **Run tests**: `pytest tests/lifecycle/ -v`
8. **Commit**: `feat: lifecycle registry, global_registry, provider (FEAT-313 TASK-1821)`

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-18
**Notes**: Created `src/navigator_eventbus/lifecycle/{registry,global_registry,provider}.py`
in the navigator-eventbus worktree
`.claude/worktrees/feat-FEAT-313-eventbus-lifecycle-extraction`. Changed
only the intra-package imports plus the `TYPE_CHECKING` `EventBus` ref
(`parrot.core.events.evb` → `navigator_eventbus.evb`); all three lazy
in-method imports in `registry.py` (provider at what was :218,
global_registry at :354/:432) kept lazy. Logger renamed to
`navigator_eventbus.lifecycle.registry`. Added
`tests/lifecycle/{test_registry,test_registry_fire_and_forget,
test_global_registry,test_provider}.py` (25 new tests; 40 total passing
in `tests/lifecycle/`). Verified during testing that `SubscriberErrorEvent`
is always routed through `get_global_registry()` (never the emitting
registry itself) — tests use `scope()` accordingly. `ruff check` clean.
`grep -r "from parrot\|import parrot"` on the three new src files → 0
hits. Committed in navigator-eventbus as `35b289f` (source
ai-parrot@3357bf4a4096959c2c8d96025b15d8e44b5b94bf).

**Deviations from spec**: none
