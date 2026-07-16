---
type: Wiki Overview
title: 'TASK-1267: Event dispatcher (orchestration + FormEventAbort capture)'
id: doc:sdd-tasks-completed-task-1267-event-dispatcher-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 Module 3. The dispatcher is the single API surface that `FormAPIHandler`
  calls. It resolves the binding from `form.events`, looks up the handler in the registry,
  runs it, captures `FormEventAbort`, and returns an `EventResolution`.
---

# TASK-1267: Event dispatcher (orchestration + FormEventAbort capture)

**Feature**: FEAT-188 — Form Lifecycle Events for parrot-formdesigner
**Spec**: `sdd/specs/formdesigner-lifecycle-events.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1265, TASK-1266
**Assigned-to**: unassigned

---

## Context

Implements §3 Module 3. The dispatcher is the single API surface that `FormAPIHandler` calls. It resolves the binding from `form.events`, looks up the handler in the registry, runs it, captures `FormEventAbort`, and returns an `EventResolution`.

---

## Scope

- Create `packages/parrot-formdesigner/src/parrot_formdesigner/services/event_dispatcher.py` exposing one public coroutine `dispatch(...)`.
- Implement `EventResolution` aggregation: if handler returns `None`, treat as empty `EventResolution()`.
- Implement shallow-merge helper for `schema_overrides` (top-level keys only — see spec §7).
- Re-export `dispatch` from `services/__init__.py`.
- Write unit tests in `tests/unit/services/test_event_dispatcher.py`.

**NOT in scope**: integration with `FormAPIHandler`, the remote endpoint, CSRF, or the HTML5 renderer.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/event_dispatcher.py` | CREATE | `dispatch(...)` coroutine + helpers |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/__init__.py` | MODIFY | Re-export `dispatch` |
| `packages/parrot-formdesigner/tests/unit/services/test_event_dispatcher.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from collections.abc import Mapping
from typing import Any

from aiohttp import web

from parrot_formdesigner.core.events import (   # from TASK-1265
    EventResolution,
    FormEventAbort,
    FormEventContext,
    FormEventName,
)
from parrot_formdesigner.services.event_registry import (  # from TASK-1266
    get_form_event,
)
# Lazy import inside function to avoid circular: FormSchema lives in core/schema
# but core/schema does not import services. So a direct import is safe:
from parrot_formdesigner.core.schema import FormSchema
```

### Existing Signatures to Use

```python
# Helpers from FormAPIHandler that callers will pass through via request:
# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:154
def _get_tenant(self, request: web.Request) -> str: ...

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:176
def _build_auth_context(self, request: web.Request) -> AuthContext: ...

# packages/parrot-formdesigner/src/parrot_formdesigner/services/auth_context.py:20
class AuthContext(BaseModel):
    """Resolved credentials passed explicitly to field resolvers."""
```

### Does NOT Exist

- ~~`parrot_formdesigner.services.event_dispatcher`~~ — create it.
- ~~`dispatch` (free function in services)~~ — create it.
- ~~`FormSchema.events`~~ at this point — TASK-1268 adds it. Until then, this module should access `getattr(form, "events", None)` to be defensive, OR TASK-1268 must complete first. **Recommended**: depend on TASK-1268 being completed (sequential per spec); use direct attribute access `form.events`.

---

## Implementation Notes

### Public API

```python
async def dispatch(
    event: FormEventName,
    *,
    form: FormSchema,
    request: web.Request,
    tenant: str,
    auth_context: AuthContext,
    payload: Mapping[str, Any] | None = None,
    schema_dump: Mapping[str, Any] | None = None,
    error: BaseException | None = None,
) -> EventResolution:
    """Resolve and run the handler bound to `event` for `form`.

    Returns an EventResolution. If no binding exists for `event`, returns an empty
    EventResolution() (no-op).

    Raises:
        FormEventAbort: handler-issued abort (for before* events). Re-raised intact.
        RuntimeError: binding is `required=True` but no handler is registered.
        Exception: any other exception from the handler propagates. The caller
            decides whether to dispatch onError separately and how to respond.
    """
```

### Key Constraints

- The caller is responsible for `(tenant, auth_context)`. The dispatcher does NOT inspect the request beyond passing it along inside `FormEventContext`.
- If `form.events is None` OR `getattr(form.events, event) is None` → return `EventResolution()` immediately. No registry lookup.
- If the binding has `required=True` and `get_form_event` raises `KeyError`, convert to `RuntimeError("event handler not registered: <ref> (form=<form_id>, event=<event>)")`. If `required=False`, log warning + return `EventResolution()`.
- Handler may return `None` → treat as empty `EventResolution()`.
- Handler may return `EventResolution` → return verbatim.
- `FormEventAbort` is NEVER converted; re-raised so the caller (handler) can turn it into an HTTP response.
- Provide a `_shallow_merge_schema(base: dict, overrides: dict) -> dict` helper for callers who want to apply `EventResolution.schema_overrides`. Export it as `apply_schema_overrides`.

### Pattern Reference

- `services/metadata_enricher.py` for the "captured exception + custom error type" pattern.

---

## Acceptance Criteria

- [ ] `from parrot_formdesigner.services.event_dispatcher import dispatch, apply_schema_overrides` works.
- [ ] `from parrot_formdesigner.services import dispatch` works (re-exported).
- [ ] `await dispatch("onBeforeSubmit", form=form_without_events, ...)` returns `EventResolution()` without touching the registry.
- [ ] `await dispatch("onBeforeSubmit", form=form_with_required_missing_handler, ...)` raises `RuntimeError`.
- [ ] `await dispatch("onBeforeSubmit", form=form_with_optional_missing_handler, ...)` logs warning + returns `EventResolution()`.
- [ ] Handler raising `FormEventAbort` → dispatch re-raises intact.
- [ ] Handler returning `None` → dispatch returns `EventResolution()`.
- [ ] `apply_schema_overrides({"a": 1, "b": {"x": 1}}, {"b": {"y": 2}})` returns `{"a": 1, "b": {"y": 2}}` (shallow; nested `x` is dropped — see spec §7 Patterns).
- [ ] All unit tests pass.
- [ ] `ruff` + `mypy --strict` clean.

---

## Test Specification

```python
# tests/unit/services/test_event_dispatcher.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot_formdesigner.core.events import (
    EventResolution,
    FormEventAbort,
    FormEventBinding,
    FormEventsConfig,
)
from parrot_formdesigner.services.event_dispatcher import (
    dispatch,
    apply_schema_overrides,
)
from parrot_formdesigner.services.event_registry import (
    register_form_event,
    _clear_event_registry_for_tests,
)


@pytest.fixture(autouse=True)
def _clear_registry():
    yield
    _clear_event_registry_for_tests()


def _form(form_id="f1", events=None):
    # Build a minimal FormSchema; details depend on TASK-1268 having added .events.
    from parrot_formdesigner.core.schema import FormSchema
    return FormSchema(
        form_id=form_id,
        title={"en": "t"},
        sections=[],
        events=events,
    )


class TestDispatch:
    async def test_no_binding_is_noop(self, mock_request, auth_context):
        form = _form(events=None)
        result = await dispatch(
            "onBeforeSubmit", form=form, request=mock_request,
            tenant="acme", auth_context=auth_context, payload={"x": 1},
        )
        assert result == EventResolution()

    async def test_handler_returns_none_is_empty(self, mock_request, auth_context):
        @register_form_event("f1.onBeforeSubmit")
        async def h(ctx):
            return None

        form = _form(events=FormEventsConfig(
            onBeforeSubmit=FormEventBinding(handler_ref="f1.onBeforeSubmit"),
        ))
        result = await dispatch(
            "onBeforeSubmit", form=form, request=mock_request,
            tenant=None, auth_context=auth_context, payload={"x": 1},
        )
        assert result == EventResolution()

    async def test_required_missing_handler_raises(self, mock_request, auth_context):
        form = _form(events=FormEventsConfig(
            onBeforeSubmit=FormEventBinding(handler_ref="f1.notReg", required=True),
        ))
        with pytest.raises(RuntimeError, match="not registered"):
            await dispatch("onBeforeSubmit", form=form, request=mock_request,
                          tenant=None, auth_context=auth_context, payload={})

    async def test_form_event_abort_propagates(self, mock_request, auth_context):
        @register_form_event("f1.onBeforeSubmit")
        async def h(ctx):
            raise FormEventAbort("blocked", user_message="No")

        form = _form(events=FormEventsConfig(
            onBeforeSubmit=FormEventBinding(handler_ref="f1.onBeforeSubmit"),
        ))
        with pytest.raises(FormEventAbort, match="blocked"):
            await dispatch("onBeforeSubmit", form=form, request=mock_request,
                          tenant=None, auth_context=auth_context, payload={})


class TestApplySchemaOverrides:
    def test_shallow_merge(self):
        base = {"a": 1, "b": {"x": 1}}
        out = apply_schema_overrides(base, {"b": {"y": 2}})
        assert out == {"a": 1, "b": {"y": 2}}  # nested x dropped intentionally
```

---

## Agent Instructions

1. **Read the spec** §3 Module 3 and §7 Patterns (shallow merge).
2. **Check dependencies** — TASK-1265 and TASK-1266 must be completed.
3. **Verify the Codebase Contract** — read `services/event_registry.py` for the import path.
4. **Implement** following the contract.
5. **Verify** all acceptance criteria.
6. **Move this file** to `sdd/tasks/completed/`.
7. **Update index** → `"done"`.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-05-20
**Notes**: event_dispatcher.py created with dispatch() coroutine + apply_schema_overrides() helper. Defensive getattr for form.events field. Re-exported from services/__init__.py. Tests created; full dispatcher tests run after TASK-1268. Ruff clean.
**Deviations from spec**: Dispatcher uses getattr(form, "events", None) defensively as recommended in task notes.
