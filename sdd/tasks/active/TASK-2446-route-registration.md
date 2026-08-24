# TASK-2446: Route Registration for /file-upload

**Feature**: FEAT-460 — Raw Upload Field Types
**Spec**: `sdd/specs/raw-upload-field-types.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2445
**Assigned-to**: unassigned

---

## Context

This task registers the new `/file-upload` endpoint in the aiohttp route table.
The handler itself is implemented in TASK-2445; this task only wires the route.
Implements **Module 4** from the spec.

---

## Scope

- Register `POST /api/v1/{tenant}/forms/{form_uid}/fields/{field_uid}/file-upload`
  in `setup_form_api` function in `api/routes.py`.
- Import `handle_file_upload` from `api/file_upload.py`.
- Wrap the handler with `_wrap_auth` following the existing REST upload route pattern.

**NOT in scope**: The handler implementation (TASK-2445), validator changes (TASK-2447).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | Add route registration |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# api/routes.py already imports from api/ modules — add file_upload to the pattern
from parrot_formdesigner.api import file_upload as file_upload_module  # created by TASK-2445
```

### Existing Signatures to Use
```python
# parrot_formdesigner/api/routes.py:165
def setup_form_api(app: web.Application, *, prefix: str = "/api/v1") -> None:
    """Register all form-related routes."""
    ...

# Existing REST upload route pattern at lines 374-377:
# app.router.add_post(
#     f"{tp}/forms/{{form_uid}}/fields/{{field_uid}}/upload",
#     _wrap_auth(uploads_module.handle_rest_upload),
# )
```

### Does NOT Exist
- ~~`/file-upload` route~~ — not registered yet; this task adds it
- ~~`file_upload_module`~~ — not imported in routes.py yet

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the REST upload route pattern at routes.py:374-377
# Add immediately after the existing upload route:
app.router.add_post(
    f"{tp}/forms/{{form_uid}}/fields/{{field_uid}}/file-upload",
    _wrap_auth(file_upload_module.handle_file_upload),
)
```

### Key Constraints
- Import `file_upload` module at the top of `setup_form_api` alongside other lazy imports (follow existing pattern)
- Use `_wrap_auth` decorator for authentication consistency
- Route path must match spec: `.../fields/{field_uid}/file-upload`
- Place the new route immediately after the existing REST upload route for logical grouping

---

## Acceptance Criteria

- [ ] Route `POST .../fields/{field_uid}/file-upload` registered in `setup_form_api`
- [ ] Handler wrapped with `_wrap_auth`
- [ ] Import of `file_upload` module added
- [ ] Existing routes unchanged (no regression)
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`

---

## Test Specification

No dedicated unit test file — route registration is verified by the integration test in TASK-2451.
Manual verification: start the app and confirm `POST .../file-upload` responds (not 404).

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/raw-upload-field-types.spec.md` for full context
2. **Check dependencies** — verify TASK-2445 is completed
3. **Verify the Codebase Contract** — read `api/routes.py`, find the existing upload route
4. **Update status** in `sdd/tasks/index/raw-upload-field-types.json` → `"in-progress"`
5. **Implement** the route registration
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2446-route-registration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
