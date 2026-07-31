---
type: Wiki Overview
title: 'TASK-1251: Route Registration for Partial Saves'
id: doc:sdd-tasks-completed-task-1251-partial-save-routes-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task wires the new handler methods into the aiohttp route table (Spec
  §3
---

# TASK-1251: Route Registration for Partial Saves

**Feature**: FEAT-186 — FormDesigner Partial Saves
**Spec**: `sdd/specs/formdesigner-partial-saves.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1249
**Assigned-to**: unassigned

---

## Context

This task wires the new handler methods into the aiohttp route table (Spec §3
Module 5). It extends `setup_form_api()` with a new `partial_store` parameter
and registers 3 new routes with auth wrapping.

---

## Scope

- Modify `setup_form_api()` to accept `partial_store: "PartialSaveStore | None" = None`
- Pass `partial_store` to `FormAPIHandler` constructor
- Register 3 new routes:
  - `POST {bp}/forms/{form_id}/partial` → `handler.save_partial`
  - `GET {bp}/forms/{form_id}/partial` → `handler.get_partial`
  - `DELETE {bp}/forms/{form_id}/partial` → `handler.delete_partial`
- All routes wrapped with `_wrap_auth()`
- Optionally stash `partial_store` on `app["partial_store"]` for lifecycle management

**NOT in scope**: Handler implementation (TASK-1249), store implementation (TASK-1248).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | Add partial_store param + 3 routes |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already in routes.py
from aiohttp import web  # verified: api/routes.py:30
from ..services.registry import FormRegistry  # verified: api/routes.py:36
from .handlers import FormAPIHandler  # verified: api/routes.py:41

# TYPE_CHECKING block already exists — add PartialSaveStore there
from ..services.partial_saves import PartialSaveStore  # TASK-1248 creates this
```

### Existing Signatures to Use
```python
# api/routes.py:59
def _wrap_auth(handler: _Handler) -> _Handler:
    """Wraps handler with is_authenticated + user_session."""

# api/routes.py:84
def setup_form_api(
    app: web.Application,
    registry: FormRegistry,
    *,
    client: "AbstractClient | None" = None,
    submission_storage: "FormSubmissionStorage | None" = None,
    forwarder: "SubmissionForwarder | None" = None,
    base_path: str = "/api/v1",
    blob_storage: "AbstractBlobStorage | None" = None,
    resolver: "RestFieldResolver | None" = None,
) -> None:  # line 84

# Route registration pattern (routes.py:144-201):
# app.router.add_post(f"{bp}/forms/{{form_id}}/data", _wrap_auth(handler.submit_data))
# app.router.add_get(f"{bp}/forms/{{form_id}}", _wrap_auth(handler.get_form))
# app.router.add_delete(f"{bp}/forms/{{form_id}}", _wrap_auth(handler.delete_form))

# FormAPIHandler constructor (after TASK-1249 modifies it):
# FormAPIHandler(registry, client, submission_storage, forwarder, partial_store)
```

### Does NOT Exist
- ~~`setup_form_api(partial_store=...)`~~ — parameter does not exist yet (this task adds it)
- ~~`app["partial_store"]`~~ — not set yet
- ~~`handler.save_partial`~~ — created by TASK-1249

---

## Implementation Notes

### Pattern to Follow
```python
# Add to setup_form_api signature:
def setup_form_api(
    app: web.Application,
    registry: FormRegistry,
    *,
    # ... existing params ...
    partial_store: "PartialSaveStore | None" = None,  # NEW
) -> None:

# Pass to handler constructor:
handler = FormAPIHandler(
    registry=registry,
    client=client,
    submission_storage=submission_storage,
    forwarder=forwarder,
    partial_store=partial_store,  # NEW
)

# Register routes (add after the validate + data routes):
# Partial saves
app.router.add_post(
    f"{bp}/forms/{{form_id}}/partial", _wrap_auth(handler.save_partial)
)
app.router.add_get(
    f"{bp}/forms/{{form_id}}/partial", _wrap_auth(handler.get_partial)
)
app.router.add_delete(
    f"{bp}/forms/{{form_id}}/partial", _wrap_auth(handler.delete_partial)
)
```

### Key Constraints
- Keep the new `partial_store` param as the last keyword argument to minimize call-site disruption
- All 3 routes must be under `_wrap_auth()` — no unauthenticated partial saves
- Add TYPE_CHECKING import for `PartialSaveStore` (same pattern as other services)

---

## Acceptance Criteria

- [ ] `setup_form_api()` accepts `partial_store` parameter
- [ ] `FormAPIHandler` receives `partial_store` in constructor
- [ ] 3 new routes registered: POST/GET/DELETE `/forms/{form_id}/partial`
- [ ] All routes wrapped with `_wrap_auth()`
- [ ] No breaking changes to existing `setup_form_api()` call sites (param is optional)
- [ ] Routes accessible at runtime (manual or integration test verification)

---

## Test Specification

No standalone test file needed — route registration is verified by integration
tests in TASK-1252. However, verify:
- Import the module without errors
- `setup_form_api()` accepts the new param without TypeError

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-partial-saves.spec.md` §3 Module 5
2. **Check dependencies** — verify TASK-1249 is complete (handler methods exist)
3. **Read `api/routes.py`** — understand route registration pattern
4. **Add the parameter and routes** following existing patterns exactly
5. **Verify no import errors**: `python -c "from parrot_formdesigner.api.routes import setup_form_api"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: SDD Worker (Claude Sonnet 4.6)
**Date**: 2026-05-19
**Notes**: Added `partial_store: "PartialSaveStore | None" = None` to `setup_form_api()`.
Added `PartialSaveStore` to `TYPE_CHECKING` block. Passed `partial_store` to
`FormAPIHandler`. Registered POST/GET/DELETE `/forms/{form_id}/partial` routes all wrapped
with `_wrap_auth()`. Stashes `partial_store` on `app["partial_store"]` for lifecycle
management. Import and route verification passed.

**Deviations from spec**: none
