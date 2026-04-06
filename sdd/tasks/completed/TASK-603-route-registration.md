# TASK-603: Route Registration

**Feature**: form-designer-edition
**Spec**: `sdd/specs/form-designer-edition.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-601, TASK-602
**Assigned-to**: unassigned

---

## Context

Registers the three new API routes in `setup_form_routes()`. All routes are wrapped with `_wrap_auth()` for navigator-auth protection, consistent with existing routes. Also updates `FormAPIHandler` instantiation in `setup_form_routes()` to pass through `submission_storage` and `forwarder` parameters.

Implements Spec Module 7.

---

## Scope

- Add to `setup_form_routes()`:
  - `PUT /api/v1/forms/{form_id}` → `api.update_form`
  - `PATCH /api/v1/forms/{form_id}` → `api.patch_form`
  - `POST /api/v1/forms/{form_id}/data` → `api.submit_data`
- All wrapped with `_wrap_auth()`
- Add `submission_storage` and `forwarder` parameters to `setup_form_routes()` signature
- Pass them through to `FormAPIHandler` constructor

**NOT in scope**: Implementing the handler methods (TASK-601, TASK-602)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py` | MODIFY | Add 3 routes + new params |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already in routes.py:
from aiohttp import web  # via handlers
from ..services.registry import FormRegistry  # line 18
from .api import FormAPIHandler  # line 19
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py:80
def setup_form_routes(
    app: web.Application,
    *,
    registry: FormRegistry | None = None,
    client: "AbstractClient | None" = None,
    prefix: str = "",
    protect_pages: bool = True,
) -> None:
    # line 109: if registry is None: registry = FormRegistry()
    # line 112: api = FormAPIHandler(registry=registry, client=client)
    # line 134: app.router.add_post(f"{p}/api/v1/forms", _wrap_auth(api.create_form))
    # ... etc

# Existing route registration pattern (line 134-141):
app.router.add_post(f"{p}/api/v1/forms", _wrap_auth(api.create_form))
app.router.add_get(f"{p}/api/v1/forms", _wrap_auth(api.list_forms))
app.router.add_get(f"{p}/api/v1/forms/{{form_id}}", _wrap_auth(api.get_form))
app.router.add_post(f"{p}/api/v1/forms/{{form_id}}/validate", _wrap_auth(api.validate))

# _wrap_auth helper:
def _wrap_auth(handler: _Handler) -> _Handler  # line 39
```

### Does NOT Exist
- ~~`PUT` route for forms~~ — does not exist; this task adds it
- ~~`PATCH` route for forms~~ — does not exist; this task adds it
- ~~`POST .../data` route~~ — does not exist; this task adds it
- ~~`submission_storage` param on `setup_form_routes`~~ — does not exist; this task adds it
- ~~`forwarder` param on `setup_form_routes`~~ — does not exist; this task adds it

---

## Implementation Notes

### Route Registration Pattern
Follow the exact same pattern as existing routes:
```python
# New edit routes (add after existing API routes)
app.router.add_put(f"{p}/api/v1/forms/{{form_id}}", _wrap_auth(api.update_form))
app.router.add_patch(f"{p}/api/v1/forms/{{form_id}}", _wrap_auth(api.patch_form))
app.router.add_post(f"{p}/api/v1/forms/{{form_id}}/data", _wrap_auth(api.submit_data))
```

### Updated Function Signature
```python
def setup_form_routes(
    app: web.Application,
    *,
    registry: FormRegistry | None = None,
    client: "AbstractClient | None" = None,
    prefix: str = "",
    protect_pages: bool = True,
    submission_storage: "FormSubmissionStorage | None" = None,
    forwarder: "SubmissionForwarder | None" = None,
) -> None:
```

### Updated FormAPIHandler Instantiation
```python
api = FormAPIHandler(
    registry=registry,
    client=client,
    submission_storage=submission_storage,
    forwarder=forwarder,
)
```

### Key Constraints
- Use `add_put` and `add_patch` aiohttp methods (they exist on `UrlDispatcher`)
- All new routes wrapped with `_wrap_auth()`
- New params must be keyword-only (after `*`) for backward compatibility
- Use TYPE_CHECKING for type hints of new params to avoid import cycles

---

## Acceptance Criteria

- [ ] `PUT /api/v1/forms/{form_id}` route registered
- [ ] `PATCH /api/v1/forms/{form_id}` route registered
- [ ] `POST /api/v1/forms/{form_id}/data` route registered
- [ ] All 3 routes wrapped with `_wrap_auth()`
- [ ] `setup_form_routes()` accepts `submission_storage` and `forwarder` params
- [ ] Existing callers of `setup_form_routes()` still work (backward-compatible)

---

## Test Specification

```python
# tests/test_routes.py
import pytest
from aiohttp import web
from parrot.formdesigner.handlers.routes import setup_form_routes
from parrot.formdesigner.services.registry import FormRegistry


class TestRouteRegistration:
    def test_setup_registers_edit_routes(self):
        app = web.Application()
        setup_form_routes(app, registry=FormRegistry())
        routes = [r.resource.canonical for r in app.router.routes() if hasattr(r, 'resource') and r.resource]
        assert "/api/v1/forms/{form_id}" in routes  # GET, PUT, PATCH
        assert "/api/v1/forms/{form_id}/data" in routes  # POST

    def test_setup_backward_compat(self):
        """Old calls without new params still work."""
        app = web.Application()
        setup_form_routes(app, registry=FormRegistry())
        # Should not raise
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-designer-edition.spec.md`
2. **Check dependencies** — verify TASK-601 and TASK-602 are in `tasks/completed/`
3. **Verify the Codebase Contract** — read `handlers/routes.py` in full
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the scope above
6. **Run tests**: `pytest packages/parrot-formdesigner/tests/test_routes.py -v`
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
