---
type: Wiki Overview
title: 'TASK-1171: App bootstrap wiring (`blob_storage` + `rest_resolver` kwargs)'
id: doc:sdd-tasks-completed-task-1171-bootstrap-wiring-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wire `AbstractBlobStorage` and `RestFieldResolver` into the aiohttp
---

# TASK-1171: App bootstrap wiring (`blob_storage` + `rest_resolver` kwargs)

**Feature**: FEAT-170 — FormDesigner `FieldType.REST`
**Spec**: `sdd/specs/new-formdesigner-field-rest.spec.md` (Module 12)
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1160, TASK-1162
**Assigned-to**: unassigned

---

## Context

Wire `AbstractBlobStorage` and `RestFieldResolver` into the aiohttp
app so `handle_rest_upload` (TASK-1170) can pick them up via
`app["blob_storage"]` and `app["rest_resolver"]`. Lazy defaults so
existing callers of `setup_form_api()` keep working unchanged.

---

## Scope

- Extend `setup_form_api()` in `api/routes.py` with two new kwargs:
  - `blob_storage: AbstractBlobStorage | None = None`
  - `resolver: RestFieldResolver | None = None`
- Inside `setup_form_api`, stash both on the `app` dict:
  - `app["blob_storage"] = blob_storage`  (may be `None`; the handler
    constructs `S3BlobStorage()` lazily on first use if `None`).
  - `app["rest_resolver"] = resolver`     (same lazy pattern).
- Document the lazy-init contract in a module docstring near the
  setup function.
- Unit test that `setup_form_api()` without the new kwargs still
  succeeds (backwards-compat) and that passing the kwargs stashes
  them on `app`.

**NOT in scope**: the handler logic (TASK-1170).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | +2 kwargs + app stash |
| `packages/parrot-formdesigner/tests/unit/api/test_setup_form_api_rest.py` | CREATE | Bootstrap unit test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Signature

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py:70
def setup_form_api(
    app: web.Application,
    registry: FormRegistry,
    *,
    client: "AbstractClient | None" = None,
    submission_storage: "FormSubmissionStorage | None" = None,
    forwarder: "SubmissionForwarder | None" = None,
    base_path: str = "/api/v1",
) -> None: ...
# Add blob_storage / resolver kwargs to this signature.
```

### Verified Imports

```python
from parrot_formdesigner.services.blob_storage import AbstractBlobStorage
from parrot_formdesigner.services.rest_field_resolver import RestFieldResolver
```

### Does NOT Exist

- ~~`app["blob_storage"]` / `app["rest_resolver"]`~~ — set here.
- ~~Default `S3BlobStorage()` construction inside `setup_form_api`~~ —
  do NOT eagerly construct (defer to handler's first use).

---

## Acceptance Criteria

- [ ] `setup_form_api(app, registry)` (no new kwargs) still works.
- [ ] `setup_form_api(app, registry, blob_storage=..., resolver=...)` stashes them.
- [ ] Default app keys are present after setup (`None` allowed).
- [ ] Backwards-compat tests for existing callers pass.

---

## Test Specification

```python
from aiohttp import web
from parrot_formdesigner.api.routes import setup_form_api

def test_setup_no_kwargs_still_works():
    app = web.Application()
    setup_form_api(app, registry=...)
    assert app["blob_storage"] is None
    assert app["rest_resolver"] is None

def test_setup_with_kwargs_stashes(blob_storage_mock, resolver_mock):
    app = web.Application()
    setup_form_api(app, registry=..., blob_storage=blob_storage_mock,
                   resolver=resolver_mock)
    assert app["blob_storage"] is blob_storage_mock
    assert app["rest_resolver"] is resolver_mock
```

---

## Completion Note

Extended `setup_form_api()` with `blob_storage: AbstractBlobStorage | None = None` and `resolver: RestFieldResolver | None = None` kwargs. Both stashed on app dict as `app["blob_storage"]` and `app["rest_resolver"]`. Added lazy-init contract documentation in module docstring. Also mounted the REST upload route. Created `tests/unit/api/test_setup_form_api_rest.py` with 7 tests covering backwards compat, kwarg stashing, route mounting, and custom base_path. All tests pass.
