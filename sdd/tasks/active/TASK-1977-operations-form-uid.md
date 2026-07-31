# TASK-1977: Operations endpoint path param update

**Feature**: FEAT-389 — Stable UUID-Based Form Identity
**Spec**: `sdd/specs/form-uid-stable-identity.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: TASK-1973, TASK-1976
**Assigned-to**: unassigned

---

## Context

The operations endpoint handles bulk form operations (copy, export, import,
etc.). It currently extracts `form_id` from the request path. It must be
updated to use `form_uid` with proper UUID validation, consistent with the
API handler changes in TASK-1976. Implements Module 5 from the spec.

---

## Scope

- Update `handle_operations()` to extract `form_uid` from path using
  `extract_form_uid()` (imported from handlers or a shared utils module).
- Replace `form_id = request.match_info["form_id"]` with
  `form_uid = extract_form_uid(request)`.
- Update all downstream references within the function from `form_id` to
  `form_uid` for UUID-based lookups.
- Ensure operations that resolve forms use the registry's UUID-based `get()`
  method (from TASK-1973).

**NOT in scope**: Route path changes (handled by TASK-1976 when it updates
`setup_form_api()`), storage layer (TASK-1974), other API handlers.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/operations.py` | MODIFY | Update `handle_operations()` to use `form_uid` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web  # verified: used in operations.py
# After TASK-1976 creates it:
from parrot_formdesigner.api.handlers import extract_form_uid  # will exist after TASK-1976
```

### Existing Signatures to Use
```python
# api/operations.py:358
async def handle_operations(request: web.Request) -> web.Response: ...
    # form_id = request.match_info["form_id"]  -- line 374
```

### Does NOT Exist
- ~~UUID validation in operations.py~~ — does not exist. This task adds it via
  `extract_form_uid()` (created by TASK-1976).
- ~~`form_uid` references anywhere in operations.py~~ — all references are `form_id`.

---

## Implementation Notes

### Migration pattern
```python
# BEFORE (line 374):
form_id = request.match_info["form_id"]

# AFTER:
from parrot_formdesigner.api.handlers import extract_form_uid
# ... inside handle_operations():
form_uid = extract_form_uid(request)
```

### Downstream references
After extracting `form_uid`, grep within `handle_operations()` for all uses of
the old `form_id` variable that referred to the path parameter. Update them to
use `form_uid`. Be careful to distinguish:
- `form_id` from the path (now `form_uid`) — UPDATE these.
- `form_id` as a slug property on a `FormSchema` object — leave as-is (the
  model field name `form_id` is unchanged).

### Key Constraints
- This is a small task — the operations endpoint has a single extraction point.
- Import `extract_form_uid` from wherever TASK-1976 places it (likely
  `api/handlers.py` or a new `api/utils.py`).

---

## Acceptance Criteria

- [ ] `handle_operations()` uses `extract_form_uid(request)` instead of `request.match_info["form_id"]`
- [ ] Invalid UUID in operations path returns 400 JSON error
- [ ] All downstream form lookups within `handle_operations()` use `form_uid`
- [ ] Existing operations functionality is preserved (copy, export, import work)

---

## Test Specification
```python
import pytest

@pytest.mark.asyncio
async def test_operations_with_valid_uid(client):
    """Operations endpoint accepts valid form_uid."""
    uid = "550e8400-e29b-41d4-a716-446655440000"
    resp = await client.post(f"/api/v1/forms/{uid}/operations", json={"op": "export"})
    assert resp.status in (200, 404)  # 200 if form exists, 404 if not

@pytest.mark.asyncio
async def test_operations_with_invalid_uid(client):
    """Operations endpoint rejects invalid UUID with 400."""
    resp = await client.post("/api/v1/forms/not-a-uuid/operations", json={"op": "export"})
    assert resp.status == 400
```

---

## Agent Instructions

1. Read this task file and the spec (Module 5).
2. Read `api/operations.py` in full.
3. Verify TASK-1976 is complete (`extract_form_uid()` exists).
4. Grep for all `form_id` references in `operations.py` to identify what to change.
5. Implement all scope items.
6. Run existing tests: `pytest packages/parrot-formdesigner/tests/ -v -k operations`
7. Commit with message: `sdd: TASK-1977 — operations endpoint form_uid update`
8. Update this task status to `done`.

---

## Completion Note
*(Agent fills this in when done)*
