---
type: Wiki Overview
title: 'TASK-1269: Wire onBeforeOpen and onSchemaLoaded into read handlers'
id: doc:sdd-tasks-completed-task-1269-handlers-read-hooks-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements §3 Module 5 partially — the read-side hooks. Wires:'
---

# TASK-1269: Wire onBeforeOpen and onSchemaLoaded into read handlers

**Feature**: FEAT-188 — Form Lifecycle Events for parrot-formdesigner
**Spec**: `sdd/specs/formdesigner-lifecycle-events.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1267, TASK-1268
**Assigned-to**: unassigned

---

## Context

Implements §3 Module 5 partially — the read-side hooks. Wires:
- `FormAPIHandler.get_form` (api/handlers.py:503) → `onBeforeOpen` dispatch.
- `FormAPIHandler.get_schema` (api/handlers.py:512) → `onSchemaLoaded` dispatch (with shallow schema-overrides application).

Submit-path hooks (`onBeforeSubmit`, `onAfterSubmit`, `onError`) live in TASK-1270 because they share the try/except envelope logic.

---

## Scope

- In `get_form` (l.503): after `await self.registry.get(...)` and the 404 check, `await dispatch("onBeforeOpen", form=form, request=request, tenant=tenant, auth_context=self._build_auth_context(request))`.
- In `get_schema` (l.512): after `rendered = await self.schema_renderer.render(form)`, dispatch `onSchemaLoaded` with `schema_dump=rendered.content`. If the resolution returns `schema_overrides`, apply via `apply_schema_overrides(rendered.content, overrides)` and return the merged dict.
- For both handlers, catch `FormEventAbort` and convert to JSON response with the `status_code` and `user_message`.
- Add integration tests in `tests/integration/test_lifecycle_events_get.py`.

**NOT in scope**: `submit_data` flow, `onError`, the remote endpoint, HTML5 renderer changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | Insert dispatch calls in `get_form` (l.503) and `get_schema` (l.512) |
| `packages/parrot-formdesigner/tests/integration/test_lifecycle_events_get.py` | CREATE | Integration tests for the two read paths |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Add to api/handlers.py (top of file or near existing service imports):
from parrot_formdesigner.services.event_dispatcher import (
    dispatch,
    apply_schema_overrides,
)
from parrot_formdesigner.core.events import FormEventAbort
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:34
class FormAPIHandler:
    def _get_tenant(self, request: web.Request) -> str: ...           # line 154
    def _build_auth_context(self, request: web.Request) -> AuthContext: ...  # line 176

    async def get_form(self, request: web.Request) -> web.Response:
        """GET /api/v1/forms/{form_id} — Get full FormSchema as JSON."""
        # line 503
        form_id = request.match_info["form_id"]                # line 505
        tenant = self._get_tenant(request)                     # line 506
        form = await self.registry.get(form_id, tenant=tenant) # line 507
        if form is None:                                       # line 508
            return web.json_response({"error": ...}, status=404)
        return web.json_response(form.model_dump())            # line 510

    async def get_schema(self, request: web.Request) -> web.Response:
        """GET /api/v1/forms/{form_id}/schema — Get JSON Schema (structural)."""
        # line 512
        # ... loads form, then:
        rendered: RenderedForm = await self.schema_renderer.render(form)  # line 519
        return web.json_response(rendered.content)                          # line 520
```

### Does NOT Exist

- ~~`HandlerView`~~ — the class is `FormAPIHandler` (api/handlers.py:34).
- ~~`self.dispatcher` / `self.event_dispatcher`~~ — `dispatch` is a free function, not a method.

---

## Implementation Notes

### Insertion shape for `get_form`

```python
async def get_form(self, request: web.Request) -> web.Response:
    form_id = request.match_info["form_id"]
    tenant = self._get_tenant(request)
    form = await self.registry.get(form_id, tenant=tenant)
    if form is None:
        return web.json_response({"error": f"Form '{form_id}' not found"}, status=404)

    # NEW: lifecycle onBeforeOpen
    try:
        await dispatch(
            "onBeforeOpen",
            form=form, request=request,
            tenant=tenant,
            auth_context=self._build_auth_context(request),
        )
    except FormEventAbort as exc:
        return web.json_response(
            {"error": exc.user_message, "reason": exc.reason},
            status=exc.status_code,
        )

    return web.json_response(form.model_dump())
```

### Insertion shape for `get_schema`

```python
async def get_schema(self, request: web.Request) -> web.Response:
    # ... (load form, 404 check unchanged) ...
    rendered: RenderedForm = await self.schema_renderer.render(form)

    # NEW: lifecycle onSchemaLoaded
    try:
        resolution = await dispatch(
            "onSchemaLoaded",
            form=form, request=request,
            tenant=tenant,
            auth_context=self._build_auth_context(request),
            schema_dump=rendered.content,
        )
    except FormEventAbort as exc:
        return web.json_response(
            {"error": exc.user_message, "reason": exc.reason},
            status=exc.status_code,
        )

    content = rendered.content
    if resolution.schema_overrides:
        content = apply_schema_overrides(content, dict(resolution.schema_overrides))
    return web.json_response(content)
```

### Key Constraints

- Use `try/except FormEventAbort` ONLY — do NOT catch generic `Exception` in this task. (`onError` is a TASK-1270 concern; read-side hooks should propagate other exceptions to the framework so they surface as 500.)
- The `EventResolution.payload` field is irrelevant here (read endpoints have no payload). Ignore it.
- Do NOT change the response envelope for forms without `events` configured — they still get a plain `web.json_response(form.model_dump())` (byte-identical, see spec §5 acid test).

### References in Codebase

- `services/event_dispatcher.py` (TASK-1267) — `dispatch` and `apply_schema_overrides`.
- `core/events.py` (TASK-1265) — `FormEventAbort`.

---

## Acceptance Criteria

- [ ] `get_form` for a form WITHOUT `events` returns byte-identical response to pre-change.
- [ ] `get_form` for a form WITH `onBeforeOpen` binding registered → handler invoked.
- [ ] Handler raising `FormEventAbort(reason="x", user_message="No", status_code=403)` → HTTP 403 with body `{"error": "No", "reason": "x"}`.
- [ ] `get_schema` returns the schema unchanged if no `onSchemaLoaded` binding.
- [ ] `get_schema` applies `schema_overrides` shallowly when a handler returns them.
- [ ] All new integration tests pass.
- [ ] All existing `api/handlers.py`-related tests still pass.
- [ ] `ruff` clean.

---

## Test Specification

```python
# tests/integration/test_lifecycle_events_get.py
import pytest
from parrot_formdesigner.core.events import (
    EventResolution, FormEventAbort, FormEventBinding, FormEventsConfig,
)
from parrot_formdesigner.services.event_registry import (
    register_form_event, _clear_event_registry_for_tests,
)


@pytest.fixture(autouse=True)
def _clear():
    yield
    _clear_event_registry_for_tests()


async def test_get_form_with_no_events_unchanged(api_client, form_no_events):
    resp = await api_client.get(f"/api/v1/forms/{form_no_events.form_id}")
    assert resp.status == 200

async def test_get_form_onbeforeopen_abort_returns_403(api_client, form_with_open_hook):
    @register_form_event("f1.onBeforeOpen")
    async def block(ctx):
        raise FormEventAbort("gated", user_message="Access denied", status_code=403)

    resp = await api_client.get(f"/api/v1/forms/{form_with_open_hook.form_id}")
    assert resp.status == 403
    body = await resp.json()
    assert body == {"error": "Access denied", "reason": "gated"}

async def test_get_schema_applies_shallow_overrides(api_client, form_with_schema_hook):
    @register_form_event("f1.onSchemaLoaded")
    async def mutate(ctx):
        return EventResolution(schema_overrides={"title": "Overridden"})

    resp = await api_client.get(f"/api/v1/forms/{form_with_schema_hook.form_id}/schema")
    body = await resp.json()
    assert body["title"] == "Overridden"
```

---

## Agent Instructions

1. **Read the spec** §3 Module 5 (read-side portion) and §2 Component Diagram.
2. **Check dependencies** — TASK-1267 and TASK-1268.
3. **Verify the Codebase Contract** — read `api/handlers.py` around lines 503 and 512 to confirm the current shape before editing.
4. **Implement** — minimal in-place edits.
5. **Verify** acceptance criteria.
6. **Move** this file to `sdd/tasks/completed/`.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-05-20
**Notes**: onBeforeOpen wired into get_form, onSchemaLoaded wired into get_schema. FormEventAbort caught and converted to HTTP response. FormField import moved to module level (pre-existing ruff issue fixed). 10 integration tests passing. Ruff clean.
**Deviations from spec**: Minor — FormField moved to top-level import (pre-existing ruff warning); handler_refs in tests use underscores not hyphens (regex constraint).
