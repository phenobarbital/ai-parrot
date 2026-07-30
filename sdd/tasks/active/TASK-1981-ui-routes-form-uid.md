# TASK-1981: UI routes path param update

**Feature**: FEAT-389 — Stable UUID-Based Form Identity
**Spec**: `sdd/specs/form-uid-stable-identity.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: TASK-1973
**Assigned-to**: unassigned

---

## Context

The UI routes serve HTML pages for form editing, previewing, and Telegram
integration. They currently use `{form_id}` (mutable slug) in URL paths.
They must be migrated to `{form_uid}` (immutable UUID) so that bookmarked
or shared URLs remain stable across form renames. Implements Module 9 from
the spec.

---

## Scope

- Rename `{form_id}` to `{form_uid}` in ALL UI route paths in `ui/routes.py`.
- Update all UI page handlers to extract `form_uid` from `request.match_info`.
- Add UUID validation to UI route handlers (reuse `extract_form_uid()` from
  TASK-1976 or implement equivalent inline validation).
- Update any template rendering calls that pass `form_id` from the path
  to instead pass `form_uid`.

**NOT in scope**: API routes (TASK-1976), operations (TASK-1977), template
HTML changes (templates reference form data from context, not URL params).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/ui/routes.py` | MODIFY | Rename `{form_id}` to `{form_uid}` in all UI route paths, update handlers |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web  # verified: used in ui/routes.py
```

### Existing Signatures to Use
```python
# ui/routes.py — route registrations with {form_id} path params:
# /forms/{form_id}/schema          — line 96
# /forms/{form_id}                 — line 100
# POST /forms/{form_id}            — line 104
# /forms/{form_id}/telegram        — line 110
# /api/v1/forms/{form_id}/telegram-submit  — line 114
```

### Does NOT Exist
- ~~UUID validation in UI routes~~ — does not exist. This task adds it.
- ~~`form_uid` in any UI route path~~ — all paths use `{form_id}`.

---

## Implementation Notes

### Route migration pattern
```python
# BEFORE (line 96):
app.router.add_get("/forms/{form_id}/schema", handle_schema_page)
# AFTER:
app.router.add_get("/forms/{form_uid}/schema", handle_schema_page)
```

Apply this to ALL routes listed in the codebase contract.

### Handler extraction pattern
```python
# BEFORE:
form_id = request.match_info["form_id"]
# AFTER:
form_uid = request.match_info["form_uid"]
# Optionally validate UUID format:
try:
    uuid.UUID(form_uid)
except ValueError:
    raise web.HTTPBadRequest(text="Invalid form_uid")
```

### Reusing `extract_form_uid()`
If TASK-1976 has placed `extract_form_uid()` in a shared location
(e.g., `api/handlers.py` or `api/utils.py`), import and use it:
```python
from parrot_formdesigner.api.handlers import extract_form_uid
```
If it is tightly coupled to the API module, implement a lightweight
equivalent inline or in a shared utility.

### Template context
UI handlers likely pass `form_id` to template rendering:
```python
context = {"form_id": form_id, ...}
```
Update to also pass `form_uid`:
```python
context = {"form_uid": form_uid, "form_id": schema.form_id, ...}
```

### Key Constraints
- The Telegram submit endpoint (`/api/v1/forms/{form_id}/telegram-submit`)
  is a public-facing URL that external Telegram bots may reference.
  Renaming it is a breaking change — document this in the completion note
  and consider a redirect or backward-compat route.
- All 5 route paths must be updated consistently.

---

## Acceptance Criteria

- [ ] All UI route paths use `{form_uid}` instead of `{form_id}`
- [ ] All UI handlers extract `form_uid` from `request.match_info`
- [ ] UUID validation is applied (400 on invalid UUID)
- [ ] Template rendering context includes `form_uid`
- [ ] Telegram submit route updated (with note about breaking change)
- [ ] All 5 route registrations updated consistently

---

## Test Specification
```python
import pytest

@pytest.mark.asyncio
async def test_ui_schema_page_with_uid(client):
    """GET /forms/{form_uid}/schema serves the schema page."""
    uid = "550e8400-e29b-41d4-a716-446655440000"
    resp = await client.get(f"/forms/{uid}/schema")
    assert resp.status in (200, 404)  # 200 if form exists

@pytest.mark.asyncio
async def test_ui_form_page_with_uid(client):
    """GET /forms/{form_uid} serves the form page."""
    uid = "550e8400-e29b-41d4-a716-446655440000"
    resp = await client.get(f"/forms/{uid}")
    assert resp.status in (200, 404)

@pytest.mark.asyncio
async def test_ui_invalid_uid_returns_400(client):
    """GET /forms/not-a-uuid returns 400."""
    resp = await client.get("/forms/not-a-uuid")
    assert resp.status == 400

@pytest.mark.asyncio
async def test_telegram_route_with_uid(client):
    """GET /forms/{form_uid}/telegram serves telegram page."""
    uid = "550e8400-e29b-41d4-a716-446655440000"
    resp = await client.get(f"/forms/{uid}/telegram")
    assert resp.status in (200, 404)
```

---

## Agent Instructions

1. Read this task file and the spec (Module 9).
2. Read `ui/routes.py` in full.
3. Verify TASK-1973 is complete (`FormRegistry` reindexed on `form_uid`).
4. Grep for all `{form_id}` patterns and `match_info["form_id"]` in `ui/`.
5. Implement all scope items.
6. Run existing tests: `pytest packages/parrot-formdesigner/tests/ -v -k ui`
7. Add new tests per test specification.
8. Commit with message: `sdd: TASK-1981 — UI routes path param to form_uid`
9. Update this task status to `done`.

---

## Completion Note
*(Agent fills this in when done)*
