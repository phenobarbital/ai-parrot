# TASK-1976: API routes and handlers — path param and UUID validation

**Feature**: FEAT-389 — Stable UUID-Based Form Identity
**Spec**: `sdd/specs/form-uid-stable-identity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-1973
**Assigned-to**: unassigned

---

## Context

All API routes currently use `{form_id}` (a mutable slug) as the path parameter.
They must be migrated to `{form_uid}` (immutable UUID) as the primary identifier.
A UUID validation helper prevents invalid UUIDs from reaching the storage layer.
A new `POST /forms/blank` endpoint and `?slug=` query support are also added.
Implements Module 4 from the spec.

---

## Scope

- Rename `{form_id}` to `{form_uid}` in ALL route paths in `setup_form_api()`.
- Change all `request.match_info["form_id"]` to `request.match_info["form_uid"]`
  in handler methods (~18 locations across handlers.py).
- Add `extract_form_uid(request) -> str` helper function:
  - Extracts `form_uid` from `request.match_info`.
  - Validates it is a well-formed UUID (regex or `uuid.UUID()` parse).
  - Returns 400 JSON error response if invalid.
- Add `POST /forms/blank` route in `setup_form_api()`.
- Add `create_blank_form()` handler:
  - Creates a new `FormSchema` with auto-generated `form_uid` and minimal defaults.
  - Returns the new form's `form_uid` in the response.
- Add `?slug=` query parameter support on `list_forms()`:
  - If `slug` query param is present, filter results by `form_id` (slug match).
  - Uses `FormRegistry.get_by_slug()` from TASK-1973.

**NOT in scope**: Storage layer changes (TASK-1974), operations endpoint (TASK-1977),
UI routes (TASK-1981).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | Rename `{form_id}` to `{form_uid}` in all route paths, add `POST /forms/blank` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | Update all `match_info["form_id"]` to `match_info["form_uid"]`, add `extract_form_uid()`, add `create_blank_form()` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# routes.py
from aiohttp import web  # verified: used throughout routes.py
# handlers.py
from parrot_formdesigner.services.registry import FormRegistry  # verified: handlers.py imports
from parrot_formdesigner.core.schema import FormSchema  # verified: handlers.py imports
import uuid  # stdlib — add for UUID validation
```

### Existing Signatures to Use
```python
# api/routes.py:94
def setup_form_api(app: web.Application, ...): ...
    # Route definitions at lines 207-213, e.g.:
    # app.router.add_get(f"{bp}/forms/{{form_id}}", handler.get_form)
    # app.router.add_put(f"{bp}/forms/{{form_id}}", handler.update_form)
    # app.router.add_delete(f"{bp}/forms/{{form_id}}", handler.delete_form)
    # ... (~6-8 route lines using {form_id})

# api/handlers.py:46
class FormAPIHandler:
    # __init__: line 76
    def __init__(self, registry: FormRegistry, ...): ...

    # create_form: line 745
    async def create_form(self, request: web.Request) -> web.Response: ...

    # get_form: line 569
    async def get_form(self, request: web.Request) -> web.Response: ...
        # form_id = request.match_info["form_id"]  -- line 571
```

### Does NOT Exist
- ~~`extract_form_uid()`~~ — does not exist. This task creates it.
- ~~`create_blank_form()`~~ — does not exist. This task creates it.
- ~~`POST /forms/blank` route~~ — does not exist. This task adds it.
- ~~`?slug=` query parameter on list_forms~~ — does not exist. This task adds it.

---

## Implementation Notes

### `extract_form_uid()` helper
```python
import uuid as _uuid

def extract_form_uid(request: web.Request) -> str:
    """Extract and validate form_uid from request path.

    Raises web.HTTPBadRequest if form_uid is not a valid UUID.
    """
    form_uid = request.match_info["form_uid"]
    try:
        _uuid.UUID(form_uid)
    except ValueError:
        raise web.HTTPBadRequest(
            text='{"error": "Invalid form_uid: must be a valid UUID"}',
            content_type="application/json",
        )
    return form_uid
```

### Route migration pattern
```python
# BEFORE:
app.router.add_get(f"{bp}/forms/{{form_id}}", handler.get_form)
# AFTER:
app.router.add_get(f"{bp}/forms/{{form_uid}}", handler.get_form)
```

### `POST /forms/blank` route
Place BEFORE the `{form_uid}` catch-all routes to avoid path conflicts:
```python
app.router.add_post(f"{bp}/forms/blank", handler.create_blank_form)
# ... then the parameterized routes:
app.router.add_get(f"{bp}/forms/{{form_uid}}", handler.get_form)
```

### Handler migration pattern
Replace every occurrence:
```python
# BEFORE:
form_id = request.match_info["form_id"]
# AFTER:
form_uid = extract_form_uid(request)
```

### `?slug=` on list_forms
```python
async def list_forms(self, request: web.Request) -> web.Response:
    slug = request.query.get("slug")
    if slug:
        # Use registry.get_by_slug(slug, tenant=...)
        ...
```

### Key Constraints
- `POST /forms/blank` must be registered BEFORE `{form_uid}` routes so
  the literal "blank" is not captured as a UUID path param.
- All ~18 `match_info["form_id"]` locations must be updated — grep thoroughly.
- UUID validation must return a proper JSON error, not an HTML error page.

---

## Acceptance Criteria

- [ ] All route paths in `setup_form_api()` use `{form_uid}` instead of `{form_id}`
- [ ] All handler methods use `request.match_info["form_uid"]`
- [ ] `extract_form_uid()` validates UUID format, returns 400 on invalid
- [ ] `POST /forms/blank` route exists and is registered before parameterized routes
- [ ] `create_blank_form()` handler creates a form with auto-generated `form_uid`
- [ ] `list_forms()` supports `?slug=` query parameter
- [ ] Invalid UUID in path returns JSON 400 error (not 500 or HTML)
- [ ] All existing API tests updated to use `form_uid` in URLs

---

## Test Specification
```python
import pytest
from aiohttp.test_utils import AioHTTPTestCase

@pytest.mark.asyncio
async def test_get_form_by_uid(client):
    """GET /forms/{form_uid} returns the correct form."""
    uid = "550e8400-e29b-41d4-a716-446655440000"
    resp = await client.get(f"/api/v1/forms/{uid}")
    assert resp.status == 200

@pytest.mark.asyncio
async def test_invalid_uuid_returns_400(client):
    """GET /forms/not-a-uuid returns 400."""
    resp = await client.get("/api/v1/forms/not-a-uuid")
    assert resp.status == 400
    body = await resp.json()
    assert "error" in body

@pytest.mark.asyncio
async def test_create_blank_form(client):
    """POST /forms/blank creates a form with generated form_uid."""
    resp = await client.post("/api/v1/forms/blank")
    assert resp.status in (200, 201)
    body = await resp.json()
    assert "form_uid" in body

@pytest.mark.asyncio
async def test_list_forms_with_slug_filter(client):
    """GET /forms?slug=my-form filters by slug."""
    resp = await client.get("/api/v1/forms?slug=my-form")
    assert resp.status == 200

@pytest.mark.asyncio
async def test_blank_route_not_captured_as_uid(client):
    """POST /forms/blank is not treated as form_uid='blank'."""
    resp = await client.post("/api/v1/forms/blank")
    assert resp.status != 400  # Should not fail UUID validation
```

---

## Agent Instructions

1. Read this task file and the spec (Module 4).
2. Read `api/routes.py` and `api/handlers.py` in full.
3. Verify TASK-1973 is complete (`FormRegistry.get_by_slug()` exists).
4. Grep for ALL occurrences of `match_info["form_id"]` in the `api/` directory.
5. Implement all scope items.
6. Run existing tests: `pytest packages/parrot-formdesigner/tests/ -v -k api`
7. Add new tests per test specification.
8. Commit with message: `sdd: TASK-1976 — API routes and handlers path param to form_uid`
9. Update this task status to `done`.

---

## Completion Note
*(Agent fills this in when done)*
