---
type: Wiki Overview
title: 'TASK-1266: Tenant-scoped event registry (mirror of callback_registry)'
id: doc:sdd-tasks-completed-task-1266-event-registry-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements §3 Module 2 of the spec: the tenant-scoped registry where users
  register lifecycle event handlers via `@register_form_event(...)`. Structural mirror
  of `services/callback_registry.py` — same fallback semantics, same helper shape,
  same exception behavior on duplicate re'
---

# TASK-1266: Tenant-scoped event registry (mirror of callback_registry)

**Feature**: FEAT-188 — Form Lifecycle Events for parrot-formdesigner
**Spec**: `sdd/specs/formdesigner-lifecycle-events.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1265
**Assigned-to**: unassigned

---

## Context

Implements §3 Module 2 of the spec: the tenant-scoped registry where users register lifecycle event handlers via `@register_form_event(...)`. Structural mirror of `services/callback_registry.py` — same fallback semantics, same helper shape, same exception behavior on duplicate registration.

---

## Scope

- Create `packages/parrot-formdesigner/src/parrot_formdesigner/services/event_registry.py` containing:
  - Module-level dict `_EVENT_REGISTRY: dict[tuple[str | None, str], FormEventHandler]`.
  - `FormEventHandler` type alias for `Callable[..., Awaitable[EventResolution | None]]`.
  - `register_form_event(handler_ref, *, tenant=None)` decorator.
  - `get_form_event(handler_ref, *, tenant=None)` lookup with tenant → global fallback.
  - `list_form_events(tenant=None)` introspection helper.
  - `_clear_event_registry_for_tests()` test-only helper.
- Re-export public symbols from `services/__init__.py`.
- Write unit tests in `packages/parrot-formdesigner/tests/unit/services/test_event_registry.py`.

**NOT in scope**: dispatcher, schema changes, handlers, renderer.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/event_registry.py` | CREATE | Registry module (mirror of `callback_registry.py`) |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/__init__.py` | MODIFY | Re-export `register_form_event`, `get_form_event`, `list_form_events`, `_clear_event_registry_for_tests` |
| `packages/parrot-formdesigner/tests/unit/services/test_event_registry.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Imports this task needs:
import asyncio  # for iscoroutinefunction check
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from parrot_formdesigner.core.events import EventResolution  # created in TASK-1265
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/callback_registry.py
# This is the EXACT pattern to mirror. Read it before implementing.
RestCallback = Callable[..., Awaitable[Any]]                  # line 48
_CALLBACK_REGISTRY: dict[tuple[str | None, str], RestCallback] # line 53

def register_form_callback(
    name: str,
    *,
    tenant: str | None = None,
) -> Callable[[RestCallback], RestCallback]: ...               # line 60

def get_form_callback(
    name: str,
    *,
    tenant: str | None = None,
) -> RestCallback: ...                                          # line 130

def list_form_callbacks(
    tenant: str | None = None,
) -> list[tuple[str | None, str]]: ...                          # line 161

def _clear_registry_for_tests() -> None: ...                    # line 187
```

### Does NOT Exist

- ~~`parrot_formdesigner.services.event_registry`~~ — create it.
- ~~`register_form_event`, `get_form_event`, `list_form_events`~~ — create them.
- ~~`_EVENT_REGISTRY`, `_clear_event_registry_for_tests`~~ — create them.

---

## Implementation Notes

### Pattern to Follow

Open `services/callback_registry.py` and copy the structure VERBATIM, then:
- Rename `_CALLBACK_REGISTRY` → `_EVENT_REGISTRY`.
- Rename `RestCallback` → `FormEventHandler` (return type is `EventResolution | None`).
- Rename `register_form_callback` → `register_form_event`, `get_form_callback` → `get_form_event`, etc.
- Rename `_clear_registry_for_tests` → `_clear_event_registry_for_tests`.
- Add an additional guard: `if not asyncio.iscoroutinefunction(fn): raise TypeError("handler must be async")` inside the decorator (the callback_registry does not do this — for events it is a hard requirement).

### Key Constraints

- The `(tenant, handler_ref)` key tuple shape MUST match `callback_registry` exactly (so a future refactor could merge bases).
- Tenant string `"None"` (literal string) must raise `ValueError` (collision with `None` sentinel) — same guard as callback_registry.
- Duplicate `(tenant, handler_ref)` → `ValueError`. NO silent override.
- Module is **module-level state** (not thread-local). Tests must clear it via the helper fixture.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/services/callback_registry.py` — the source-of-truth pattern.
- `packages/parrot-formdesigner/tests/unit/services/test_callback_registry.py` — copy the test structure and adapt.

---

## Acceptance Criteria

- [ ] `from parrot_formdesigner.services.event_registry import register_form_event, get_form_event, list_form_events, _clear_event_registry_for_tests` works.
- [ ] `from parrot_formdesigner.services import register_form_event` works (re-exported).
- [ ] Registering a sync function raises `TypeError` ("handler must be async").
- [ ] Registering twice with the same `(tenant, handler_ref)` raises `ValueError`.
- [ ] `get_form_event("x.y", tenant="acme")` returns the tenant-specific handler if present.
- [ ] `get_form_event("x.y", tenant="acme")` falls back to the global handler when no tenant-specific is registered.
- [ ] `get_form_event("missing.ref")` raises `KeyError`.
- [ ] `list_form_events(tenant="acme")` returns both global and acme-scoped keys.
- [ ] Tests in `tests/unit/services/test_event_registry.py` pass with `-v`.
- [ ] `ruff` + `mypy --strict` clean on the new file.

---

## Test Specification

```python
# tests/unit/services/test_event_registry.py
import pytest
from parrot_formdesigner.services.event_registry import (
    register_form_event,
    get_form_event,
    list_form_events,
    _clear_event_registry_for_tests,
)
from parrot_formdesigner.core.events import EventResolution


@pytest.fixture(autouse=True)
def _clear_registry():
    yield
    _clear_event_registry_for_tests()


class TestRegisterFormEvent:
    async def test_global_registration_and_lookup(self):
        @register_form_event("survey_v1.onBeforeSubmit")
        async def h(ctx):
            return EventResolution()

        assert get_form_event("survey_v1.onBeforeSubmit") is h

    async def test_tenant_overrides_global(self):
        @register_form_event("a.b")
        async def global_h(ctx):
            return EventResolution()

        @register_form_event("a.b", tenant="acme")
        async def acme_h(ctx):
            return EventResolution()

        assert get_form_event("a.b", tenant="acme") is acme_h
        assert get_form_event("a.b", tenant="other") is global_h

    def test_duplicate_raises(self):
        @register_form_event("a.b")
        async def first(ctx):
            return EventResolution()

        with pytest.raises(ValueError, match="already registered"):
            @register_form_event("a.b")
            async def second(ctx):
                return EventResolution()

    def test_sync_handler_rejected(self):
        with pytest.raises(TypeError, match="async"):
            @register_form_event("a.b")
            def sync_h(ctx):
                return None

    def test_tenant_string_None_rejected(self):
        with pytest.raises(ValueError, match="None"):
            @register_form_event("a.b", tenant="None")
            async def h(ctx):
                return None

    def test_missing_handler_keyerror(self):
        with pytest.raises(KeyError):
            get_form_event("does.not.exist")
```

---

## Agent Instructions

1. **Read the spec** §3 Module 2.
2. **Check dependencies** — TASK-1265 must be completed.
3. **Verify the Codebase Contract** — open `services/callback_registry.py` and confirm line numbers.
4. **Update status** in the index.
5. **Implement** by mirroring `callback_registry.py`.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-05-20
**Notes**: event_registry.py created as structural mirror of callback_registry.py. Async-only guard added. Re-exported from services/__init__.py. 16 unit tests passing. Ruff clean.
**Deviations from spec**: none
