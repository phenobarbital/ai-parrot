---
type: Wiki Overview
title: 'Feature Specification: FormDesigner — Clone Form'
id: doc:sdd-specs-formdesigner-clone-form-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Users and integrations frequently need to create a new form that is a variation
---

---
type: feature
base_branch: dev
---

# Feature Specification: FormDesigner — Clone Form

**Feature ID**: FEAT-183
**Date**: 2026-05-18
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

Users and integrations frequently need to create a new form that is a variation
of an existing one — e.g., cloning a "Customer Feedback" form to create a
"Partner Feedback" form with a different title, tweaked fields, or a different
submit action. Today, the only way to achieve this is to export the full JSON,
manually change `form_id` and any other fields, and re-import. This is
error-prone and requires the caller to understand the entire FormSchema
structure.

### Goals

- Provide a first-class `clone_form` operation at the **storage**, **registry**,
  and **REST API** layers.
- The caller supplies a `new_form_id` (required) and an optional RFC 7396
  merge-patch dict to override any top-level or nested fields on the cloned
  copy.
- The cloned form always starts at version `"1.0"` — it is a new form with its
  own lifecycle.
- The clone is persisted (when storage is configured) and registered in-memory
  in a single call.

### Non-Goals (explicitly out of scope)

- Cloning across tenants in a single call (the caller can clone within a
  tenant, then re-save to another tenant via existing APIs).
- Cloning submission history — only the schema is cloned.
- Deep "template" system with inheritance — the clone is a fully independent
  copy; changes to the source do not propagate.

---

## 2. Architectural Design

### Overview

A `clone_form` operation performs a deep copy of an existing `FormSchema`,
replaces the `form_id` with a caller-supplied value, resets the version to
`"1.0"`, optionally applies an RFC 7396 merge-patch (reusing the existing
`_deep_merge` utility), validates the result with `FormValidator`, and then
persists + registers the new form.

The operation is exposed at three layers:

1. **`FormStorage.clone`** — new abstract method on the ABC, implemented by
   `PostgresFormStorage`. Uses `load` + mutate + `save` (no SQL-level
   `INSERT ... SELECT` — keeps the operation in Pydantic-land for consistency).
2. **`FormRegistry.clone_form`** — orchestrates the full flow: load → deep copy
   → patch → validate → register + persist.
3. **`POST /api/v1/forms/{form_id}/clone`** — REST endpoint delegating to
   `FormRegistry.clone_form`.

### Component Diagram

```
REST: POST /forms/{form_id}/clone
        │
        ▼
FormAPIHandler.clone_form(request)
        │
        ▼
FormRegistry.clone_form(source_id, new_form_id, patch?, tenant?)
        │
        ├── registry.get(source_id)          ← load from memory
        ├── model_copy(deep=True)            ← Pydantic deep clone
        ├── _deep_merge(cloned, patch)       ← apply caller overrides
        ├── FormValidator.check_schema()     ← structural validation
        └── registry.register(persist=True)  ← memory + DB
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FormStorage` (ABC) | extends | Add optional `clone` method with default impl |
| `PostgresFormStorage` | extends | Override `clone` for efficiency |
| `FormRegistry` | extends | New `clone_form` async method |
| `FormAPIHandler` | extends | New `clone_form` handler method |
| `routes.setup_form_api` | extends | Register `POST .../clone` route |
| `_deep_merge` | uses | RFC 7396 merge-patch for overrides |
| `FormValidator` | uses | Structural validation on the cloned form |
| `FormCache` | indirect | Cache is populated via `registry.register` |

### Data Models

No new Pydantic models are required. The clone operation works entirely with
the existing `FormSchema` model. The REST endpoint accepts a JSON body:

```python
# Request body for POST /api/v1/forms/{form_id}/clone
{
    "new_form_id": str,       # required — slug for the cloned form
    "patch": dict | None,     # optional — RFC 7396 merge-patch
    "tenant": str | None,     # optional — tenant override for the clone
}
```

### New Public Interfaces

```python
# FormRegistry (parrot_formdesigner/services/registry.py)
class FormRegistry:
    async def clone_form(
        self,
        source_form_id: str,
        new_form_id: str,
        patch: dict[str, Any] | None = None,
        *,
        persist: bool = True,
        tenant: str | None = None,
    ) -> FormSchema:
        """Clone an existing form under a new form_id."""
        ...

# FormAPIHandler (parrot_formdesigner/api/handlers.py)
class FormAPIHandler:
    async def clone_form(self, request: web.Request) -> web.Response:
        """POST /api/v1/forms/{form_id}/clone"""
        ...
```

---

## 3. Module Breakdown

### Module 1: FormRegistry.clone_form

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py`
- **Responsibility**: Orchestrate the full clone flow — load source, deep copy,
  apply optional patch, validate, register with persist.
- **Depends on**: `FormSchema.model_copy`, `_deep_merge`, `FormValidator`

### Module 2: PostgresFormStorage — no ABC change needed

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py`
- **Responsibility**: No new method on `FormStorage` ABC is needed. The clone
  operation is fully handled by `FormRegistry.clone_form` which calls existing
  `registry.get` + `registry.register(persist=True)`. The storage layer
  receives the final `FormSchema` through the existing `save` path.
- **Depends on**: existing `save` method

### Module 3: REST Endpoint — clone_form handler

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
  and `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`
- **Responsibility**: Parse request, extract `new_form_id` and optional `patch`,
  delegate to `FormRegistry.clone_form`, return the new form JSON.
- **Depends on**: Module 1

### Module 4: Unit + Integration Tests

- **Path**: `packages/parrot-formdesigner/tests/unit/test_clone_form.py`
  and `packages/parrot-formdesigner/tests/integration/test_clone_rest.py`
- **Responsibility**: Full test coverage for the clone operation.
- **Depends on**: Modules 1–3

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_clone_basic` | Module 1 | Clone a form, verify new form_id and version 1.0 |
| `test_clone_deep_copy` | Module 1 | Mutating the clone does not affect the source |
| `test_clone_with_patch` | Module 1 | Apply merge-patch (title, description, field changes) |
| `test_clone_patch_cannot_change_form_id` | Module 1 | Patch with `form_id` key is ignored |
| `test_clone_source_not_found` | Module 1 | Raises/returns error when source does not exist |
| `test_clone_duplicate_form_id` | Module 1 | Error when new_form_id already exists |
| `test_clone_validation_error` | Module 1 | Patch that produces invalid schema returns error |
| `test_clone_resets_version` | Module 1 | Cloned form always has version "1.0" |
| `test_clone_resets_created_at` | Module 1 | Cloned form has `created_at=None` (storage sets it) |

### Integration Tests

| Test | Description |
|---|---|
| `test_clone_rest_endpoint` | POST /clone returns 200 with the new form |
| `test_clone_rest_missing_new_form_id` | POST /clone returns 400 when new_form_id missing |
| `test_clone_rest_source_not_found` | POST /clone returns 404 for unknown source |
| `test_clone_rest_with_patch` | POST /clone with patch body applies overrides |
| `test_clone_rest_duplicate_id` | POST /clone returns 409 when new_form_id exists |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_form() -> FormSchema:
    return FormSchema(
        form_id="source-form",
        title="Source Form",
        version="2.3",
        sections=[
            FormSection(
                section_id="sec1",
                title="Section 1",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label="Full Name",
                        required=True,
                    ),
                ],
            ),
        ],
    )
```

---

## 5. Acceptance Criteria

- [x] `FormRegistry.clone_form` creates a deep copy with new `form_id`, version
  `"1.0"`, and `created_at=None`.
- [x] Optional RFC 7396 merge-patch is applied to the cloned form before
  validation.
- [x] `form_id` in the patch dict is ignored — the `new_form_id` argument wins.
- [x] `FormValidator.check_schema` runs on the clone; errors are surfaced.
- [x] The cloned form is registered in-memory and persisted (when storage is
  configured) in a single call.
- [x] `POST /api/v1/forms/{form_id}/clone` endpoint exists and is protected by
  navigator-auth.
- [x] Returns 404 when the source form does not exist.
- [x] Returns 409 when `new_form_id` already exists in the registry.
- [x] Returns 400 when `new_form_id` is missing from the body.
- [x] All unit tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_clone_form.py -v`
- [x] All integration tests pass: `pytest packages/parrot-formdesigner/tests/integration/test_clone_rest.py -v`
- [ ] No breaking changes to existing FormStorage ABC (clone is a concrete
  method with default impl, not a new abstract method).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField  # verified: core/schema.py:153,101,23
from parrot_formdesigner.core.types import FieldType  # verified: core/types.py
from parrot_formdesigner.services.registry import FormRegistry, FormStorage  # verified: services/registry.py:116,29
from parrot_formdesigner.services.storage import PostgresFormStorage  # verified: services/storage.py:55
from parrot_formdesigner.services.validators import FormValidator  # verified: services/__init__.py:11
from parrot_formdesigner.api._utils import _deep_merge, _bump_version  # verified: api/_utils.py:11,61
from parrot_formdesigner.api.handlers import FormAPIHandler  # verified: api/handlers.py:33
```

### Existing Class Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormSchema(BaseModel):
    form_id: str                              # line 178
    version: str = "1.0"                      # line 179
    title: LocalizedString                    # line 180
    description: LocalizedString | None = None  # line 181
    sections: list[FormSection]               # line 182
    submit: SubmitAction | None = None        # line 183
    cancel_allowed: bool = True               # line 184
    meta: dict[str, Any] | None = None        # line 185
    created_at: datetime | None = None        # line 186
    tenant: str | None = None                 # line 187
    # Pydantic v2 — model_copy(deep=True) for deep cloning
    # model_dump() → dict, model_validate(data) → FormSchema

# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormRegistry:                           # line 116
    def __init__(self, storage: FormStorage | None = None) -> None:  # line 133
    async def register(self, form: FormSchema, *, persist: bool = False, overwrite: bool = True) -> None:  # line 146
    async def get(self, form_id: str) -> FormSchema | None:  # line 214
    async def contains(self, form_id: str) -> bool:  # line 244

class FormStorage(ABC):                       # line 29
    async def save(self, form: FormSchema, style=None, *, tenant=None) -> str:  # line 39
    async def load(self, form_id: str, version=None, *, tenant=None) -> FormSchema | None:  # line 60

# packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py
class FormValidator:
    def check_schema(self, form: FormSchema) -> list[str]:  # returns error strings

# packages/parrot-formdesigner/src/parrot_formdesigner/api/_utils.py
def _deep_merge(base: dict, patch: dict) -> dict:  # line 11 — RFC 7396 merge-patch
def _bump_version(version: str) -> str:             # line 61

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
class FormAPIHandler:                          # line 33
    def __init__(self, registry, client=None, submission_storage=None, forwarder=None):  # line 51
    # All handler methods: async def xxx(self, request: web.Request) -> web.Response

# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
def setup_form_api(app, registry, *, client=None, ...):  # line 84
    # Registers routes on app.router via app.router.add_post(...)
def _wrap_auth(handler: _Handler) -> _Handler:  # line 59 — navigator-auth wrapper
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `FormRegistry.clone_form` | `FormRegistry.get` | method call | `services/registry.py:214` |
| `FormRegistry.clone_form` | `FormSchema.model_copy(deep=True)` | Pydantic v2 | `core/schema.py:153` |
| `FormRegistry.clone_form` | `_deep_merge` | function call | `api/_utils.py:11` |
| `FormRegistry.clone_form` | `FormValidator.check_schema` | method call | `services/validators.py` |
| `FormRegistry.clone_form` | `FormRegistry.register` | method call | `services/registry.py:146` |
| `FormAPIHandler.clone_form` | `FormRegistry.clone_form` | method call | (new) |
| `setup_form_api` | `FormAPIHandler.clone_form` | route registration | `api/routes.py:136` |

### Does NOT Exist (Anti-Hallucination)

- ~~`FormStorage.clone`~~ — there is no clone method on the ABC; the clone
  operation is orchestrated entirely at the `FormRegistry` level.
- ~~`FormSchema.clone()`~~ — no such method; use `model_copy(deep=True)`.
- ~~`FormRegistry.duplicate`~~ — does not exist.
- ~~`FormAPIHandler.duplicate_form`~~ — does not exist.
- ~~`parrot_formdesigner.api.clone`~~ — no such module.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Use `model_copy(deep=True)` for deep cloning, consistent with how
  `EditToolkit.__init__` (line 83) and `handle_operations` (line 418) both
  deep-clone `FormSchema`.
- Use `_deep_merge` from `api/_utils.py` for the optional merge-patch, matching
  the existing `patch_form` handler pattern.
- Follow the same handler pattern as `create_form` / `edit_form` — return
  `{"form_id": ..., "title": ..., "url": ...}`.
- Protect the endpoint with `_wrap_auth` in `routes.py`, matching all other
  endpoints.
- Use `self.logger` throughout, following existing logging patterns.

### Known Risks / Gotchas

- **form_id collision**: The caller must provide a `new_form_id` that does not
  already exist. The implementation must check `registry.contains(new_form_id)`
  before saving and return 409 Conflict if it already exists.
- **Patch producing invalid schema**: A merge-patch could introduce invalid
  field types, break section structure, etc. Always run
  `FormValidator.check_schema` on the result and return 422 on errors.
- **created_at leakage**: The cloned form must have `created_at=None` so the
  storage layer assigns a fresh timestamp. If the patch includes
  `created_at`, it should be stripped.

### External Dependencies

No new external dependencies required.

---

## 8. Open Questions

- [ ] Should the clone endpoint return the full FormSchema body or just the
  summary (`form_id`, `title`, `url`)? — *Owner: Jesus*: return the full FormSchema
- [ ] Should we add a `cloned_from` field to `FormSchema.meta` for
  provenance tracking? — *Owner: Jesus*: yes

---

## Worktree Strategy

- **Isolation unit**: per-spec (sequential tasks)
- All 4 modules are sequential (each depends on the previous).
- No cross-feature dependencies — this spec is self-contained within
  `parrot-formdesigner`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-18 | Jesus Lara | Initial draft |
