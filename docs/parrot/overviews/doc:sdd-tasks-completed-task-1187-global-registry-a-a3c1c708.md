---
type: Wiki Overview
title: 'TASK-1187: Implement global registry singleton and scope() context manager'
id: doc:sdd-tasks-completed-task-1187-global-registry-and-scope-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 6 of the spec. The global registry is a process-wide `EventRegistry`
  singleton that observes every event (unless an agent opts out via `forward_to_global=False`).
  The `scope()` context manager swaps it for a fresh registry during the block — required
  for test isolation, es
relates_to:
- concept: mod:parrot.core.events.lifecycle.global_registry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.registry
  rel: mentions
---

# TASK-1187: Implement global registry singleton and scope() context manager

**Feature**: FEAT-176 — Lifecycle Events System
**Spec**: `sdd/specs/FEAT-176-lifecycle-events-system.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: TASK-1186
**Assigned-to**: unassigned

---

## Context

Module 6 of the spec. The global registry is a process-wide `EventRegistry` singleton that observes every event (unless an agent opts out via `forward_to_global=False`). The `scope()` context manager swaps it for a fresh registry during the block — required for test isolation, especially under pytest parallelism. Storage uses `contextvars.ContextVar` so each asyncio task sees a coherent registry.

Spec section: §2 New Public Interfaces (lines 413–427) and §3 Module 6.

---

## Scope

- Implement `get_global_registry()` returning a process-wide singleton `EventRegistry`.
- Implement `scope()` as a `@contextmanager` that swaps the global registry with a fresh `EventRegistry(forward_to_global=False)` for the block, then restores the previous one.
- Use `contextvars.ContextVar[EventRegistry]` so that nested `scope()` blocks and concurrent asyncio tasks see independent registries.
- Add unit tests covering: singleton identity, scope isolation, nested scopes, scope cleanup on exception.

**NOT in scope**: `EventEmitterMixin` (TASK-1189), tests for end-to-end meta-event propagation (those live in integration tests added later).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/lifecycle/global_registry.py` | CREATE | Singleton + `scope()` ctx manager. |
| `packages/ai-parrot/tests/unit/events/lifecycle/test_global_registry.py` | CREATE | Singleton + scope tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

from parrot.core.events.lifecycle.registry import EventRegistry   # TASK-1186
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
```

### Does NOT Exist

- ~~`module-level globals` (e.g. `_GLOBAL_REGISTRY = EventRegistry()`)~~ — must use `ContextVar` for asyncio-task safety.
- ~~`threading.local`~~ — wrong tool; we're in asyncio land. `ContextVar` is correct.

---

## Implementation Notes

### Recommended structure

```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/global_registry.py
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

from parrot.core.events.lifecycle.registry import EventRegistry


_GLOBAL_REGISTRY: ContextVar[Optional[EventRegistry]] = ContextVar(
    "parrot_lifecycle_global_registry",
    default=None,
)


def get_global_registry() -> EventRegistry:
    """Return the process-wide singleton EventRegistry.

    Lazily constructs on first call. Subsequent calls return the same
    instance until a `scope()` block replaces it.
    """
    reg = _GLOBAL_REGISTRY.get()
    if reg is None:
        # Global registry never forwards to itself — would cause infinite recursion.
        reg = EventRegistry(forward_to_global=False)
        _GLOBAL_REGISTRY.set(reg)
    return reg


@contextmanager
def scope() -> Iterator[EventRegistry]:
    """Replace the global registry with a fresh one for the duration of
    the block. Restores the previous registry on exit, even if the block
    raises. Required for test isolation."""
    fresh = EventRegistry(forward_to_global=False)
    token = _GLOBAL_REGISTRY.set(fresh)
    try:
        yield fresh
    finally:
        _GLOBAL_REGISTRY.reset(token)
```

### Why `ContextVar.set/reset` (token pattern)

Using the token returned by `ContextVar.set(...)` and `reset(token)` is the only correct way to restore the previous value — direct re-assignment loses the prior token chain and breaks nested scopes.

### Why `forward_to_global=False` on the global registry

The global registry MUST NOT forward events to itself; that would cause infinite recursion. `EventRegistry.__init__` already accepts the flag (TASK-1186).

### Key Constraints

- No module-level mutable state besides the `ContextVar`.
- Lazy construction — don't instantiate `EventRegistry` at import time.
- `scope()` must restore the previous registry even if the block raises.

---

## Acceptance Criteria

- [ ] `get_global_registry()` returns the same instance across calls within a context.
- [ ] `scope()` yields a fresh registry distinct from the outer global.
- [ ] After `scope()` exits, `get_global_registry()` returns the previous instance.
- [ ] Nested `scope()` blocks isolate correctly.
- [ ] `scope()` restores the previous registry even if the block raises.
- [ ] Unit tests pass: `pytest packages/ai-parrot/tests/unit/events/lifecycle/test_global_registry.py -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/core/events/lifecycle/global_registry.py` is clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/events/lifecycle/test_global_registry.py
import pytest

from parrot.core.events.lifecycle.global_registry import (
    get_global_registry, scope,
)
from parrot.core.events.lifecycle.registry import EventRegistry


class TestGlobalRegistry:
    def test_singleton_identity(self):
        with scope():
            a = get_global_registry()
            b = get_global_registry()
            assert a is b

    def test_scope_swaps(self):
        with scope() as outer:
            assert get_global_registry() is outer

    def test_scope_restores(self):
        with scope() as outer:
            with scope() as inner:
                assert get_global_registry() is inner
                assert inner is not outer
            assert get_global_registry() is outer

    def test_scope_restores_on_exception(self):
        with scope() as outer:
            with pytest.raises(RuntimeError):
                with scope() as inner:
                    assert get_global_registry() is inner
                    raise RuntimeError("boom")
            assert get_global_registry() is outer

    def test_global_does_not_self_forward(self):
        with scope() as reg:
            assert reg._forward_to_global is False    # internal flag check
```

---

## Agent Instructions

1. Read spec §2 lines 413–427 and §3 Module 6.
2. Confirm TASK-1186 is in `sdd/tasks/completed/` and `EventRegistry` is importable.
3. Implement the singleton + scope, run tests, update the per-spec index, move this file to `sdd/tasks/completed/`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-15
**Notes**: global_registry.py implemented exactly as specified using ContextVar token/reset pattern. 8/8 tests pass. Ruff clean. No deviations.

**Deviations from spec**: none
