---
type: Wiki Overview
title: 'TASK-1343: Pluggable Hooks Refactor (MessagingHook Protocol)'
id: doc:sdd-tasks-completed-task-1343-pluggable-hooks-refactor-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: specific messaging channel. This task refactors hooks to use a
relates_to:
- concept: mod:parrot.core.hooks
  rel: mentions
- concept: mod:parrot.core.hooks.base
  rel: mentions
- concept: mod:parrot.integrations
  rel: mentions
- concept: mod:parrot.integrations.matrix.client
  rel: mentions
---

# TASK-1343: Pluggable Hooks Refactor (MessagingHook Protocol)

**Feature**: FEAT-202 — ai-parrot-integrations
**Spec**: `sdd/specs/ai-parrot-integrations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`parrot/core/hooks/matrix.py` imports `MatrixClientWrapper` from
`parrot.integrations.matrix.client` at line 63 — coupling core to a
specific messaging channel. This task refactors hooks to use a
pluggable interface: a `MessagingHook` Protocol in `base.py` + a
registry for external hooks to self-register.

The concrete `MatrixHook` implementation will be moved to the
satellite package in TASK-1350 (matrix extraction). This task only
creates the interface + registry and removes the coupling from core.

Implements **Spec Module 11**.

---

## Scope

- Define `MessagingHook` Protocol (or abstract class extending
  `BaseHook`) in `parrot/core/hooks/base.py`.
- Add a hook registry to `parrot/core/hooks/` that allows external
  packages to register hook implementations (decorator or explicit
  `register()` call).
- Refactor `parrot/core/hooks/matrix.py` to remove the direct import
  of `MatrixClientWrapper`. Instead, the file becomes a thin wrapper
  that delegates to whatever `MessagingHook` implementation is
  registered for "matrix".
- Update `parrot/core/hooks/__init__.py` exports if needed.

**NOT in scope**: Moving `MatrixHook` to the satellite package (TASK-1350).
No changes to `HookManager` lifecycle beyond adding registry support.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/core/hooks/base.py` | MODIFY | Add `MessagingHook` Protocol and hook registry |
| `parrot/core/hooks/matrix.py` | MODIFY | Remove direct `MatrixClientWrapper` import; use registry |
| `parrot/core/hooks/__init__.py` | MODIFY | Export `MessagingHook` and registry |
| `parrot/core/hooks/models.py` | CHECK | Verify `MatrixHookConfig` stays for backward compat |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# parrot/core/hooks/base.py:12
class BaseHook(ABC):
    # abstractmethods: start(), stop()

# parrot/core/hooks/matrix.py:10-11
from .base import BaseHook
from .models import HookType, MatrixHookConfig

# parrot/core/hooks/matrix.py:14
class MatrixHook(BaseHook):
    ...

# parrot/core/hooks/matrix.py:63 (inside method — dynamic import)
from parrot.integrations.matrix.client import MatrixClientWrapper
```

### Existing Signatures to Use

```python
# parrot/core/hooks/base.py:12
class BaseHook(ABC):
    async def start(self) -> None: ...   # abstract
    async def stop(self) -> None: ...    # abstract
```

### Does NOT Exist

- ~~`parrot.core.hooks.MessagingHook`~~ — does NOT exist yet; this task creates it
- ~~`parrot.core.hooks.HookRegistry`~~ — does NOT exist yet; this task creates it
- ~~`parrot.core.hooks.register_hook`~~ — does NOT exist yet

---

## Implementation Notes

### Pattern to Follow

```python
# In parrot/core/hooks/base.py — add after BaseHook
from typing import Protocol, runtime_checkable

@runtime_checkable
class MessagingHook(Protocol):
    """Interface for messaging-channel hooks."""
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def on_message(self, message: Any) -> None: ...

class HookRegistry:
    """Registry for external hook implementations."""
    _hooks: dict[str, type[BaseHook]] = {}

    @classmethod
    def register(cls, name: str, hook_cls: type[BaseHook]) -> None:
        cls._hooks[name] = hook_cls

    @classmethod
    def get(cls, name: str) -> type[BaseHook] | None:
        return cls._hooks.get(name)
```

### Key Constraints

- `BaseHook` API must not change (backward compatible).
- `MatrixHookConfig` in `models.py` stays — it's the config schema.
- The registry must work WITHOUT the satellite package installed
  (graceful when no hooks registered).

---

## Acceptance Criteria

- [ ] `MessagingHook` Protocol defined in `parrot/core/hooks/base.py`
- [ ] `HookRegistry` with `register()` and `get()` methods
- [ ] `MatrixHook` no longer has direct `from parrot.integrations...` import
- [ ] `from parrot.core.hooks import MessagingHook, HookRegistry` works
- [ ] Existing hook functionality preserved (MatrixHook still works
      when integrations is installed)
- [ ] No linting errors: `ruff check parrot/core/hooks/`

---

## Test Specification

```python
import pytest
from parrot.core.hooks.base import MessagingHook, HookRegistry, BaseHook

def test_messaging_hook_protocol():
    assert hasattr(MessagingHook, 'start')
    assert hasattr(MessagingHook, 'stop')

def test_hook_registry_register_and_get():
    class DummyHook(BaseHook):
        async def start(self): pass
        async def stop(self): pass
    HookRegistry.register("dummy", DummyHook)
    assert HookRegistry.get("dummy") is DummyHook

def test_hook_registry_missing():
    assert HookRegistry.get("nonexistent") is None
```

---

## Agent Instructions

When you pick up this task:

1. Read `parrot/core/hooks/base.py` and `parrot/core/hooks/matrix.py` in full
2. Understand how `MatrixHook` is currently instantiated and used
3. Design the `MessagingHook` Protocol to match existing `BaseHook` interface
4. Add the registry with minimal API
5. Refactor `matrix.py` to use registry lookup instead of direct import
6. Run tests

---

## Completion Note

*(Agent fills this in when done)*
