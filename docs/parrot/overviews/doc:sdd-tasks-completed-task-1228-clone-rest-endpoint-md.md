---
type: Wiki Overview
title: 'TASK-1228: REST Endpoint — clone_form handler + route'
id: doc:sdd-tasks-completed-task-1228-clone-rest-endpoint-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task wires up the HTTP surface for form cloning. It adds a
---

# TASK-1228: REST Endpoint — clone_form handler + route

**Feature**: FEAT-183 — FormDesigner Clone Form
**Spec**: `sdd/specs/formdesigner-clone-form.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1227
**Assigned-to**: unassigned

---

## Context

This task wires up the HTTP surface for form cloning. It adds a
`clone_form` handler method to `FormAPIHandler` and registers it as
`POST /api/v1/forms/{form_id}/clone` in `setup_form_api`, protected by
navigator-auth.

Implements spec §3 Module 3.

The user resolved Open Question Q1: the endpoint returns the **full
FormSchema body** (not just the summary).

---

## Scope

- Add `async def clone_form(self, request: web.Request) -> web.Response` to
  `FormAPIHandler` in `api/handlers.py`.
- The handler must:
  1. Extract `form_id` from `request.match_info["form_id"]`.
  2. Parse JSON body; extract `new_form_id` (required), `patch` (optional
     dict), `tenant` (optional str).
  3. Return 400 if `new_form_id` is missing or empty.
  4. Call `self.registry.clone_form(form_id, new_form_id, patch, tenant=tenant)`.
  5. Catch `KeyError` → return 404 (`"Form '{form_id}' not found"`).
  6. Catch `ValueError` with "already exists" → return 409 Conflict.
  7. Catch `ValueError` with validation errors → return 422.
  8. On success, return 201 with `clone.model_dump()` (full FormSchema body
     per resolved Q1).
- Register the route in `setup_form_api` in `api/routes.py`:
  ```python
  app.router.add_post(
      f"{bp}/forms/{{form_id}}/clone", _wrap_auth(handler.clone_form)
  )
  ```
  Place it after the existing `edit_form` route and before the contract
  endpoints.

**NOT in scope**: The `FormRegistry.clone_form` method itself (TASK-1227),
tests (TASK-1229).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | Add `clone_form` handler method |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | Register POST .../clone route |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already imported in handlers.py:
import json                                    # handlers.py:13
import logging                                 # handlers.py:14
from aiohttp import web                        # handlers.py:16
from ..core.schema import FormSchema           # handlers.py:19
from ..services.registry import FormRegistry   # handlers.py:31

# Already imported in routes.py:
from aiohttp import web                        # routes.py:32
from .handlers import FormAPIHandler           # routes.py:41
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
class FormAPIHandler:                          # line 33
    registry: FormRegistry                     # set in __init__ line 58
    logger: logging.Logger                     # line 64

    # Pattern — all handlers follow this shape:
    async def create_form(self, request: web.Request) -> web.Response:   # line 294
    async def edit_form(self, request: web.Request) -> web.Response:     # line 336
    async def patch_form(self, request: web.Request) -> web.Response:    # line 433
    async def delete_form(self, request: web.Request) -> web.Response:   # line 478

# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
def setup_form_api(app, registry, ...):        # line 84
    handler = FormAPIHandler(registry=registry, ...)  # line 125
    bp = base_path.rstrip("/")                 # line 132

    # Route registration pattern:
    app.router.add_post(f"{bp}/forms", _wrap_auth(handler.create_form))      # line 136
    app.router.add_post(
        f"{bp}/forms/{{form_id}}/edit", _wrap_auth(handler.edit_form)        # line 144
    )

def _wrap_auth(handler: _Handler) -> _Handler:  # line 59

# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormRegistry:
    async def clone_form(                      # (created by TASK-1227)
        self,
        source_form_id: str,
        new_form_id: str,
        patch: dict[str, Any] | None = None,
        *,
        persist: bool = True,
        tenant: str | None = None,
    ) -> FormSchema: ...
```

### Does NOT Exist

- ~~`FormAPIHandler.clone_form`~~ — does not exist yet (you are creating it)
- ~~`FormAPIHandler.duplicate_form`~~ — does not exist
- ~~Route `/api/v1/forms/{form_id}/clone`~~ — does not exist yet

---

## Implementation Notes

### Pattern to Follow

Follow the exact same pattern as `edit_form` (line 336) and `patch_form`
(line 433): extract `form_id` from match_info, parse JSON body, call the
registry method, handle errors, return JSON response.

```python
# Reference: edit_form handler pattern (handlers.py:336-390)
async def edit_form(self, request: web.Request) -> web.Response:
    form_id = request.match_info["form_id"]
    # ... parse body, call tool, return response
```

```python
# Route registration pattern (routes.py:144-146)
app.router.add_post(
    f"{bp}/forms/{{form_id}}/edit", _wrap_auth(handler.edit_form)
)
```

### Key Constraints

- Return 201 (Created) on success — not 200, since a new resource was created.
- Return the full `FormSchema` via `clone.model_dump()` per resolved Q1.
- All error responses must use `web.json_response({"error": ...}, status=NNN)`.
- Use `self.logger.info(...)` on success, `self.logger.warning(...)` on errors.
- No new imports needed in `handlers.py` — all are already present.

---

## Acceptance Criteria

- [ ] `FormAPIHandler.clone_form` handler method exists
- [ ] Route `POST /api/v1/forms/{form_id}/clone` registered and auth-wrapped
- [ ] Returns 201 with full FormSchema JSON on success
- [ ] Returns 400 when `new_form_id` is missing or empty
- [ ] Returns 404 when source form not found
- [ ] Returns 409 when `new_form_id` already exists
- [ ] Returns 422 when patch produces invalid schema
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/`

---

## Test Specification

```python
# Tests are in TASK-1229 — this section shows expected REST behavior.

async def test_clone_rest_endpoint(aiohttp_client, registry_with_form):
    """POST /api/v1/forms/source-form/clone returns 201 with full form."""
    client = await aiohttp_client(app)
    resp = await client.post(
        "/api/v1/forms/source-form/clone",
        json={"new_form_id": "cloned-form"},
    )
    assert resp.status == 201
    data = await resp.json()
    assert data["form_id"] == "cloned-form"
    assert data["version"] == "1.0"
    assert data["meta"]["cloned_from"] == "source-form"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-clone-form.spec.md` for full context
2. **Check dependencies** — verify TASK-1227 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `FormRegistry.clone_form` exists
4. **Implement** the handler in `handlers.py` and the route in `routes.py`
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-1228-clone-rest-endpoint.md`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: SDD Worker (claude-sonnet-4-6)
**Date**: 2026-05-18
**Notes**: Added `FormAPIHandler.clone_form` handler to `handlers.py` following
the `edit_form`/`patch_form` pattern. Returns 201 with full FormSchema body on
success. Error paths: 400 (missing/empty new_form_id or invalid JSON), 404
(source not found), 409 (new_form_id exists), 422 (validation failure).
Registered `POST {bp}/forms/{form_id}/clone` route in `routes.py` wrapped with
`_wrap_auth`, placed after the edit_form route. All acceptance criteria met.

**Deviations from spec**: none
