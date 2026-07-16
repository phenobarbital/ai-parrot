---
type: Wiki Overview
title: 'TASK-1242: FormStorage `close()` + FormRegistry aiohttp Lifecycle'
id: doc:sdd-tasks-completed-task-1242-formstorage-close-and-registry-lifecycle-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the foundation task for FEAT-185. It modifies two classes in the
  same
---

# TASK-1242: FormStorage `close()` + FormRegistry aiohttp Lifecycle

**Feature**: FEAT-185 — Refactor FormRegistry
**Spec**: `sdd/specs/refactor-formregistry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundation task for FEAT-185. It modifies two classes in the same
file (`services/registry.py` in parrot-formdesigner):

1. Adds a default no-op `async def close()` to the `FormStorage` ABC so that
   `FormRegistry.on_shutdown` can call it unconditionally.
2. Refactors `FormRegistry.__init__` to accept an optional `aiohttp.web.Application`
   instance, self-register as `app['form_registry']`, and hook into
   `app.on_startup` / `app.on_shutdown` signals.

Implements spec §2 Overview, §3 Modules 1 and 3.

---

## Scope

- Add `async def close(self) -> None` to `FormStorage` ABC with a default
  no-op body (not `@abstractmethod` — subclasses override optionally).
- Modify `FormRegistry.__init__` signature to accept `app: web.Application | None = None`
  as the **first** parameter (before `storage`).
- When `app` is provided:
  - Store `self._app = app`.
  - Set `app['form_registry'] = self`.
  - Append `self.on_startup` to `app.on_startup`.
  - Append `self.on_shutdown` to `app.on_shutdown`.
- When `app` is `None`: behave exactly as before (backward compatibility).
- Add `async def on_startup(self, app: web.Application) -> None`:
  - Call `await self._storage.initialize()` if storage has an `initialize` method.
  - Call `await self.load_from_storage()` if storage is configured.
- Add `async def on_shutdown(self, app: web.Application) -> None`:
  - Call `await self._storage.close()` if storage is configured.
- Import `web` from `aiohttp` conditionally (TYPE_CHECKING) to avoid hard
  aiohttp dependency for non-web use cases.

**NOT in scope**: PostgresFormStorage changes (TASK-1243), core package mirror
(TASK-1244), call-site updates (TASK-1245), tests (TASK-1246).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py` | MODIFY | Add `close()` to `FormStorage`, refactor `FormRegistry.__init__`, add `on_startup`/`on_shutdown` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot_formdesigner.services.registry import FormStorage  # verified: services/registry.py:35
from parrot_formdesigner.services.registry import FormRegistry  # verified: services/registry.py:122
from parrot_formdesigner.core.schema import FormSchema          # verified via registry.py:23
from aiohttp import web                                         # used in routes.py:30, handlers.py — available

# For TYPE_CHECKING guard:
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from aiohttp import web
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormStorage(ABC):                                    # line 35
    @abstractmethod
    async def save(self, form, style=None, *, tenant=None) -> str:     # line 44
    @abstractmethod
    async def load(self, form_id, version=None, *, tenant=None):       # line 66
    @abstractmethod
    async def delete(self, form_id, *, tenant=None) -> bool:           # line 88
    @abstractmethod
    async def list_forms(self, *, tenant=None) -> list[dict[str, Any]]:  # line 101
    # close() does NOT exist — you are adding it

class FormRegistry:                                        # line 122
    def __init__(self, storage: FormStorage | None = None) -> None:    # line 139
    _forms: dict[str, FormSchema]                          # line 145
    _lock: asyncio.Lock                                    # line 146
    _storage: FormStorage | None                           # line 147
    _on_register: list[...]                                # line 148
    _on_unregister: list[...]                              # line 149
    logger: logging.Logger                                 # line 150

    def set_storage(self, storage: FormStorage) -> None:   # line 197
    async def load_from_storage(self, *, tenant=None) -> int:  # line 318
    @property has_storage -> bool:                         # line 357
    @property storage -> FormStorage | None:               # line 369
```

### Does NOT Exist

- ~~`FormStorage.close()`~~ — does not exist yet; you are adding it
- ~~`FormRegistry.on_startup`~~ — does not exist yet; you are adding it
- ~~`FormRegistry.on_shutdown`~~ — does not exist yet; you are adding it
- ~~`FormRegistry._app`~~ — does not exist yet; you are adding it
- ~~`FormStorage.initialize()`~~ — NOT on the ABC. Only exists on `PostgresFormStorage` (line 185 of storage.py). Use `hasattr()` to check before calling.

---

## Implementation Notes

### Pattern to Follow

aiohttp signal callbacks have the signature `async def handler(app: web.Application) -> None`.
Register them via `app.on_startup.append(coroutine)`.

```python
# Reference: aiohttp signal registration pattern
app.on_startup.append(self.on_startup)
app.on_shutdown.append(self.on_shutdown)
```

```python
# Reference: how app.py currently stashes the registry (line 242)
self.app['form_registry'] = form_registry
```

### Key Constraints

- `aiohttp` import MUST be guarded under `TYPE_CHECKING` plus a runtime
  conditional import inside `__init__` (or use `Any` for the type hint).
  This preserves the ability to use `FormRegistry` outside aiohttp contexts.
- `on_startup` must call `initialize()` only if the storage has the method
  (use `hasattr(self._storage, 'initialize')`). The ABC doesn't define it.
- `on_startup` should call `load_from_storage()` after `initialize()` to
  hydrate the in-memory cache automatically.
- `on_shutdown` calls `self._storage.close()` unconditionally (the ABC
  default is a no-op, so it's always safe).
- Preserve the existing `set_storage()` method — it may still be used.

---

## Acceptance Criteria

- [ ] `FormStorage` has `async def close(self) -> None` with a default no-op
- [ ] `FormRegistry.__init__` accepts `app: web.Application | None = None` as first param
- [ ] When `app` is provided, `app['form_registry']` is set to `self`
- [ ] When `app` is provided, `on_startup` and `on_shutdown` are appended to app signals
- [ ] `FormRegistry(storage=...)` without `app` still works (backward compat)
- [ ] `on_startup` calls `storage.initialize()` if method exists
- [ ] `on_startup` calls `load_from_storage()` after initialize
- [ ] `on_shutdown` calls `storage.close()`
- [ ] No import errors when `aiohttp` is not installed (TYPE_CHECKING guard)

---

## Test Specification

```python
# Tests are in TASK-1246 — this section shows expected behavior.
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot_formdesigner.services.registry import FormRegistry, FormStorage


async def test_registry_no_app():
    """FormRegistry works without app (backward compat)."""
    registry = FormRegistry()
    assert len(registry) == 0


async def test_registry_with_app():
    """FormRegistry registers itself in app."""
    from aiohttp.web import Application
    app = Application()
    storage = AsyncMock(spec=FormStorage)
    registry = FormRegistry(app=app, storage=storage)
    assert app['form_registry'] is registry
    assert registry.on_startup in app.on_startup
    assert registry.on_shutdown in app.on_shutdown
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/refactor-formregistry.spec.md` for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm all imports/signatures are still accurate
4. **Implement** the changes in `registry.py` following the scope above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-1242-formstorage-close-and-registry-lifecycle.md`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: SDD Worker (claude-sonnet-4-6)
**Date**: 2026-05-19
**Notes**: Added TYPE_CHECKING guard for `aiohttp.web`, added `close()` no-op to `FormStorage` ABC, updated `FormRegistry.__init__` to accept optional `app: web.Application | None = None`, added `on_startup` and `on_shutdown` signal handlers. Both signals registered via `app.on_startup.append()` / `app.on_shutdown.append()`. `on_startup` calls `initialize()` (if present via hasattr) then `load_from_storage()`. `on_shutdown` calls `storage.close()`.

**Deviations from spec**: none
