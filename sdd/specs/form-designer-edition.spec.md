# Feature Specification: Form Designer Edition (Edit API)

**Feature ID**: FEAT-086
**Date**: 2026-04-06
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.1.0

---

## 1. Motivation & Business Requirements

### Problem Statement

Once a form is created in AI-Parrot's form designer (via natural language, YAML, database import, or Pydantic extraction), there is no API to modify it. The current `FormAPIHandler` only exposes `POST /api/v1/forms` (create) and `GET` endpoints (read). Developers and end-users cannot:

- Rename field keys (`field_id`) in the result dictionary
- Change form title, description, or section structure
- Modify the submit destination (URL, HTTP method, authentication)
- Submit and store form data through the API

The only workaround is to recreate the form from scratch, which blocks any form-editing UI workflow and limits API usefulness.

### Goals
- Provide `PUT /api/v1/forms/{form_id}` for full form replacement
- Provide `PATCH /api/v1/forms/{form_id}` for partial updates (JSON merge-patch, RFC 7396)
- Provide `POST /api/v1/forms/{form_id}/data` for receiving, validating, storing, and forwarding form submissions
- Extend `SubmitAction` with pluggable auth configuration (`bearer`, `api_key`, `none`)
- Run `FormValidator.check_schema()` before persisting any edit
- Support editing both in-memory and persisted forms

### Non-Goals (explicitly out of scope)
- LLM tool for editing forms (no `EditFormTool`)
- Visual/UI form editor component
- Version history — edits bump the version string but previous versions are not retained
- Data migration when renaming field keys (only relevant for forms without collected data)
- `GET /api/v1/forms/{form_id}/data` for retrieving stored submissions (future feature)

---

## 2. Architectural Design

### Overview

Extend the existing `FormAPIHandler` with three new endpoint methods (`update_form`, `patch_form`, `submit_data`) and register corresponding routes. Introduce an `AuthConfig` discriminated union model on `SubmitAction` for configuring endpoint authentication. Add `FormSubmissionStorage` for local submission persistence and `SubmissionForwarder` for forwarding data to configured endpoints with resolved auth credentials.

### Component Diagram
```
Client (Developer / UI)
    │
    ├── PUT  /api/v1/forms/{form_id}        ──→ FormAPIHandler.update_form()
    ├── PATCH /api/v1/forms/{form_id}        ──→ FormAPIHandler.patch_form()
    └── POST /api/v1/forms/{form_id}/data    ──→ FormAPIHandler.submit_data()
                                                      │
                                          ┌───────────┼────────────────┐
                                          ▼           ▼                ▼
                                   FormValidator  FormRegistry    SubmissionForwarder
                                   .check_schema()  .register()     (aiohttp.ClientSession)
                                                      │                ▲
                                                      ▼                │
                                              FormStorage.save()   AuthConfig
                                              (if persisted)       .resolve() → navconfig
                                                                       │
                                          FormSubmissionStorage        │
                                          .store() ────────────────────┘
                                          (form_submissions table)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FormAPIHandler` | extends | Add `update_form()`, `patch_form()`, `submit_data()` methods |
| `SubmitAction` | extends | Add `auth: AuthConfig \| None = None` field |
| `FormRegistry` | uses | `register(overwrite=True)` for re-registration after edit |
| `FormStorage` / `PostgresFormStorage` | uses | Existing `save()` UPSERT for persisting edits |
| `FormValidator` | uses | `check_schema()` for structural validation before edit; `validate()` for submission data |
| `setup_form_routes()` | extends | Register PUT, PATCH, and POST data routes |
| `_wrap_auth()` | uses | Wrap new routes with navigator-auth |

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Literal


# --- Auth Configuration (discriminated union) ---

class NoAuth(BaseModel):
    """No authentication — default, backward-compatible."""
    type: Literal["none"] = "none"


class BearerAuth(BaseModel):
    """Bearer token authentication. Token resolved from env at forwarding time."""
    type: Literal["bearer"] = "bearer"
    token_env: str = Field(..., description="Environment variable name for the Bearer token")


class ApiKeyAuth(BaseModel):
    """API key authentication. Key resolved from env at forwarding time."""
    type: Literal["api_key"] = "api_key"
    key_env: str = Field(..., description="Environment variable name for the API key")
    header_name: str = Field(default="X-API-Key", description="HTTP header name for the key")


AuthConfig = NoAuth | BearerAuth | ApiKeyAuth


# --- Extended SubmitAction ---

class SubmitAction(BaseModel):
    action_type: Literal["tool_call", "endpoint", "event", "callback"]
    action_ref: str
    method: str = "POST"
    confirm_message: LocalizedString | None = None
    auth: AuthConfig | None = None  # NEW FIELD


# --- Submission Record ---

class FormSubmission(BaseModel):
    """Record of a form data submission."""
    submission_id: str
    form_id: str
    form_version: str
    data: dict[str, Any]
    is_valid: bool
    forwarded: bool = False
    forward_status: int | None = None
    forward_error: str | None = None
    created_at: datetime
```

### New Public Interfaces

```python
# services/submissions.py
class FormSubmissionStorage:
    """Persist form submissions in PostgreSQL (form_submissions table)."""
    def __init__(self, pool: asyncpg.Pool) -> None: ...
    async def initialize(self) -> None: ...
    async def store(self, submission: FormSubmission) -> str: ...


# services/forwarder.py
class SubmissionForwarder:
    """Forward validated form data to configured SubmitAction endpoints."""
    async def forward(
        self,
        data: dict[str, Any],
        submit_action: SubmitAction,
    ) -> ForwardResult: ...


class ForwardResult(BaseModel):
    """Result of forwarding a submission."""
    success: bool
    status_code: int | None = None
    error: str | None = None


# handlers/api.py — new methods on FormAPIHandler
class FormAPIHandler:
    async def update_form(self, request: web.Request) -> web.Response: ...
    async def patch_form(self, request: web.Request) -> web.Response: ...
    async def submit_data(self, request: web.Request) -> web.Response: ...
```

---

## 3. Module Breakdown

### Module 1: AuthConfig Models
- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/core/auth.py`
- **Responsibility**: Define `NoAuth`, `BearerAuth`, `ApiKeyAuth`, and `AuthConfig` union type. Each auth type has a `resolve()` method that returns HTTP headers using `navconfig.config.get()`.
- **Depends on**: `navconfig`

### Module 2: SubmitAction Extension
- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py`
- **Responsibility**: Add `auth: AuthConfig | None = None` field to `SubmitAction`. Update package `__init__.py` exports.
- **Depends on**: Module 1

### Module 3: FormSubmissionStorage
- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/services/submissions.py`
- **Responsibility**: PostgreSQL persistence for form submissions. Creates `form_submissions` table. Provides `store()` and `initialize()` methods.
- **Depends on**: `asyncpg` (existing dependency)

### Module 4: SubmissionForwarder
- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/services/forwarder.py`
- **Responsibility**: HTTP client that forwards validated submission data to the URL configured in `SubmitAction.action_ref`, using the HTTP method from `SubmitAction.method` and auth headers resolved from `AuthConfig`. Returns `ForwardResult`.
- **Depends on**: Module 1 (AuthConfig), `aiohttp.ClientSession`

### Module 5: Edit Endpoints (PUT/PATCH)
- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py`
- **Responsibility**: Add `update_form()` (PUT — full replacement) and `patch_form()` (PATCH — JSON merge-patch) methods to `FormAPIHandler`. Both validate via `FormValidator.check_schema()`, bump version, re-register in `FormRegistry`, and persist if storage is configured.
- **Depends on**: Module 2 (for SubmitAction with auth)

### Module 6: Submission Endpoint
- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py`
- **Responsibility**: Add `submit_data()` method to `FormAPIHandler`. Flow: validate data → store locally → forward to endpoint (if configured) → return composite result.
- **Depends on**: Module 3 (FormSubmissionStorage), Module 4 (SubmissionForwarder)

### Module 7: Route Registration
- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py`
- **Responsibility**: Register `PUT`, `PATCH /api/v1/forms/{form_id}` and `POST /api/v1/forms/{form_id}/data` routes with `_wrap_auth()`.
- **Depends on**: Module 5, Module 6

### Module 8: Package Exports
- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/__init__.py` and `services/__init__.py`, `core/__init__.py`
- **Responsibility**: Export new public classes (`AuthConfig`, `NoAuth`, `BearerAuth`, `ApiKeyAuth`, `FormSubmissionStorage`, `SubmissionForwarder`, `ForwardResult`, `FormSubmission`).
- **Depends on**: Modules 1-4

### Module 9: Unit and Integration Tests
- **Path**: `packages/parrot-formdesigner/tests/`
- **Responsibility**: Tests for all new functionality.
- **Depends on**: Modules 1-8

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_bearer_auth_resolve` | Module 1 | BearerAuth resolves token from env → `{"Authorization": "Bearer <token>"}` |
| `test_api_key_auth_resolve` | Module 1 | ApiKeyAuth resolves key + custom header name |
| `test_no_auth_resolve` | Module 1 | NoAuth returns empty headers |
| `test_auth_missing_env_var` | Module 1 | Raises/returns error when env var not found |
| `test_submit_action_with_auth` | Module 2 | SubmitAction accepts and serializes `auth` field |
| `test_submit_action_backward_compat` | Module 2 | SubmitAction without `auth` field still works (None default) |
| `test_submission_storage_store` | Module 3 | Store and verify a FormSubmission record |
| `test_forwarder_success` | Module 4 | Forward data to mock endpoint, verify headers and payload |
| `test_forwarder_auth_headers` | Module 4 | Bearer and API key headers correctly applied |
| `test_forwarder_endpoint_unreachable` | Module 4 | Returns ForwardResult with error, does not raise |
| `test_put_form_full_replacement` | Module 5 | PUT replaces entire form, version bumped |
| `test_put_form_id_mismatch` | Module 5 | PUT returns 400 when URL form_id != body form_id |
| `test_put_form_not_found` | Module 5 | PUT returns 404 for non-existent form |
| `test_patch_form_merge` | Module 5 | PATCH merges partial update onto existing form |
| `test_patch_form_rename_field_id` | Module 5 | PATCH with updated field_id in sections |
| `test_patch_form_validation_failure` | Module 5 | PATCH returns 422 when edit creates circular dependency |
| `test_patch_empty_body` | Module 5 | PATCH returns 400 for empty body |
| `test_patch_persisted_form` | Module 5 | PATCH on persisted form triggers storage.save() |
| `test_submit_data_valid` | Module 6 | Submit valid data → stored locally + forwarded |
| `test_submit_data_invalid` | Module 6 | Submit invalid data → 422 with validation errors |
| `test_submit_data_no_submit_action` | Module 6 | Submit data with no SubmitAction → stored locally only |
| `test_submit_data_forward_failure` | Module 6 | Forward fails → data still stored, response includes error |

### Integration Tests
| Test | Description |
|---|---|
| `test_create_edit_submit_flow` | Create form via POST, edit via PATCH, submit data via POST data — full lifecycle |
| `test_edit_persisted_form_roundtrip` | Create persisted form, edit via PUT, verify storage updated |
| `test_submit_with_auth_forwarding` | Submit data to form with bearer auth, verify forwarded request has correct headers |

### Test Data / Fixtures
```python
@pytest.fixture
def sample_form_schema() -> FormSchema:
    """A minimal valid FormSchema for testing edits."""
    return FormSchema(
        form_id="test-form",
        version="1.0",
        title="Test Form",
        sections=[
            FormSection(
                section_id="main",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label="Name",
                        required=True,
                    ),
                    FormField(
                        field_id="email",
                        field_type=FieldType.EMAIL,
                        label="Email",
                    ),
                ],
            )
        ],
    )

@pytest.fixture
def sample_submit_action_with_auth() -> SubmitAction:
    """SubmitAction with bearer auth for forwarding tests."""
    return SubmitAction(
        action_type="endpoint",
        action_ref="https://api.example.com/intake",
        method="POST",
        auth=BearerAuth(token_env="TEST_API_TOKEN"),
    )

@pytest.fixture
def registry_with_form(sample_form_schema) -> FormRegistry:
    """FormRegistry pre-loaded with a test form."""
    registry = FormRegistry()
    # Must be awaited in async test
    return registry
```

---

## 5. Acceptance Criteria

- [ ] `PUT /api/v1/forms/{form_id}` replaces a form and returns updated schema
- [ ] `PATCH /api/v1/forms/{form_id}` merges partial JSON and returns updated schema
- [ ] Both PUT and PATCH run `FormValidator.check_schema()` before accepting
- [ ] Both PUT and PATCH bump the version string automatically
- [ ] Both PUT and PATCH persist to storage when `FormRegistry` has a storage backend
- [ ] `SubmitAction.auth` supports `bearer`, `api_key`, and `none` types
- [ ] Auth credentials are resolved from env vars via `navconfig.config.get()` — never stored as raw secrets
- [ ] `POST /api/v1/forms/{form_id}/data` validates, stores locally, and forwards submissions
- [ ] Submissions are stored in `form_submissions` table even when forwarding fails
- [ ] Forward failure does not return an error status — response includes `forwarded: false` with error details
- [ ] All new endpoints are protected by `_wrap_auth()` (navigator-auth)
- [ ] Backward compatibility: existing forms without `auth` field continue to work
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] New classes exported from `parrot.formdesigner` package `__init__.py`

---

## 6. Codebase Contract

### Verified Imports
```python
# These imports have been confirmed to work (verified 2026-04-06):
from parrot.formdesigner.core.schema import FormSchema, SubmitAction, FormField, FormSection  # core/schema.py
from parrot.formdesigner.core.schema import RenderedForm  # core/schema.py:133
from parrot.formdesigner.core.types import FieldType, LocalizedString  # core/types.py
from parrot.formdesigner.core.constraints import FieldConstraints, DependencyRule  # core/constraints.py
from parrot.formdesigner.core.style import StyleSchema  # core/style.py
from parrot.formdesigner.services.registry import FormRegistry, FormStorage  # services/registry.py
from parrot.formdesigner.services.storage import PostgresFormStorage  # services/storage.py
from parrot.formdesigner.services.validators import FormValidator, ValidationResult  # services/validators.py
from parrot.formdesigner.handlers.api import FormAPIHandler  # handlers/api.py
from parrot.formdesigner.handlers.routes import setup_form_routes, _wrap_auth  # handlers/routes.py
from navconfig import config  # app.py:2 — used for env variable resolution
```

### Existing Class Signatures

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py
class SubmitAction(BaseModel):  # line 89
    action_type: Literal["tool_call", "endpoint", "event", "callback"]  # line 99
    action_ref: str  # line 100
    method: str = "POST"  # line 101
    confirm_message: LocalizedString | None = None  # line 102

class FormSchema(BaseModel):  # line 105
    form_id: str  # line 122
    version: str = "1.0"  # line 123
    title: LocalizedString  # line 124
    description: LocalizedString | None = None  # line 125
    sections: list[FormSection]  # line 126
    submit: SubmitAction | None = None  # line 127
    cancel_allowed: bool = True  # line 128
    meta: dict[str, Any] | None = None  # line 129

# packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py
class FormRegistry:  # line 94
    _forms: dict[str, FormSchema]  # line 117
    _lock: asyncio.Lock  # line 118
    _storage: FormStorage | None  # line 119
    async def register(self, form: FormSchema, *, persist: bool = False, overwrite: bool = True) -> None  # line 124
    async def get(self, form_id: str) -> FormSchema | None  # line 192
    async def contains(self, form_id: str) -> bool  # line 222

# packages/parrot-formdesigner/src/parrot/formdesigner/services/validators.py
class FormValidator:  # line 66
    def check_schema(self, form: FormSchema) -> list[str]  # line 446
    async def validate(self, form: FormSchema, data: dict[str, Any], *, locale: str = "en") -> ValidationResult  # line 87

class ValidationResult(BaseModel):  # line 52
    is_valid: bool
    errors: dict[str, list[str]]
    sanitized_data: dict[str, Any]

# packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py
class PostgresFormStorage(FormStorage):  # line 39
    UPSERT_SQL: str  # line 72 — INSERT ... ON CONFLICT (form_id, version) DO UPDATE
    async def save(self, form: FormSchema, style: StyleSchema | None = None, *, created_by: str | None = None) -> str  # line 124

# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py
class FormAPIHandler:  # line 29
    registry: FormRegistry  # set in __init__ line 50
    validator: FormValidator  # set in __init__ line 54
    _client: AbstractClient | None  # set in __init__ line 51
    async def list_forms(self, request: web.Request) -> web.Response  # line 140
    async def get_form(self, request: web.Request) -> web.Response  # line 152
    async def create_form(self, request: web.Request) -> web.Response  # line 240
    async def validate(self, request: web.Request) -> web.Response  # line 215

# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py
def setup_form_routes(app, *, registry=None, client=None, prefix="", protect_pages=True) -> None  # line 80
def _wrap_auth(handler: _Handler) -> _Handler  # line 39
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `FormAPIHandler.update_form()` | `FormRegistry.register(overwrite=True)` | method call | `services/registry.py:124` |
| `FormAPIHandler.update_form()` | `FormValidator.check_schema()` | method call | `services/validators.py:446` |
| `FormAPIHandler.patch_form()` | `FormSchema.model_dump()` / `model_validate()` | Pydantic serialization | `core/schema.py:105` |
| `FormAPIHandler.submit_data()` | `FormValidator.validate()` | method call | `services/validators.py:87` |
| `FormAPIHandler.submit_data()` | `FormSubmissionStorage.store()` | method call | NEW |
| `FormAPIHandler.submit_data()` | `SubmissionForwarder.forward()` | method call | NEW |
| `SubmissionForwarder` | `AuthConfig.resolve()` | method call | NEW |
| `AuthConfig.resolve()` | `navconfig.config.get()` | env var lookup | `app.py:2` |
| `setup_form_routes()` | `FormAPIHandler.update_form` | route registration | `handlers/routes.py:80` |
| `setup_form_routes()` | `_wrap_auth()` | auth wrapping | `handlers/routes.py:39` |

### Does NOT Exist (Anti-Hallucination)
- ~~`FormRegistry.update()`~~ — no update method; use `register(overwrite=True)`
- ~~`FormAPIHandler.update_form()`~~ — does not exist yet; must be created
- ~~`FormAPIHandler.patch_form()`~~ — does not exist yet; must be created
- ~~`FormAPIHandler.submit_data()`~~ — does not exist yet; must be created
- ~~`SubmitAction.auth`~~ — field does not exist yet; must be added
- ~~`form_submissions` table~~ — does not exist; must be created
- ~~`FormSubmissionStorage`~~ — does not exist; must be created
- ~~`SubmissionForwarder`~~ — does not exist; must be created
- ~~`AuthConfig` / `BearerAuth` / `ApiKeyAuth`~~ — do not exist; must be created
- ~~`ForwardResult`~~ — does not exist; must be created
- ~~`FormSubmission`~~ — does not exist; must be created
- ~~`parrot.formdesigner.core.auth`~~ — module does not exist; must be created
- ~~`parrot.formdesigner.services.submissions`~~ — module does not exist; must be created
- ~~`parrot.formdesigner.services.forwarder`~~ — module does not exist; must be created

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Follow the existing `FormAPIHandler` method pattern: load form from registry → process → return JSON response with appropriate status codes
- Use `ConfigDict(extra="forbid")` on new Pydantic models (consistent with `FormField`)
- Use `logging.getLogger(__name__)` for all new classes
- Async-first: use `aiohttp.ClientSession` for HTTP forwarding, never `requests`
- Auth credentials via env var references only — never store raw secrets in form schema JSONB

### JSON Merge-Patch Implementation
The PATCH endpoint uses RFC 7396 JSON merge-patch semantics:
- Incoming JSON is deep-merged onto `FormSchema.model_dump()`
- `null` values in the patch remove the corresponding key
- Arrays are replaced entirely (not merged element-by-element)
- After merge, the result is validated via `FormSchema.model_validate()` + `FormValidator.check_schema()`

Implementation: use a recursive `deep_merge(base: dict, patch: dict) -> dict` utility function. No external library needed.

### Version Bumping
Automatic version bump on every edit:
- Parse current version as `major.minor` (e.g., "1.0" → 1, 0)
- Increment minor: "1.0" → "1.1" → "1.2" ...
- If version is not in `major.minor` format, append `.1` (e.g., "1" → "1.1")

### FormSubmissionStorage Table Schema
```sql
CREATE TABLE IF NOT EXISTS form_submissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id VARCHAR(255) NOT NULL UNIQUE,
    form_id VARCHAR(255) NOT NULL,
    form_version VARCHAR(50) NOT NULL,
    data JSONB NOT NULL,
    is_valid BOOLEAN NOT NULL DEFAULT TRUE,
    forwarded BOOLEAN NOT NULL DEFAULT FALSE,
    forward_status INTEGER,
    forward_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_form_submissions_form_id ON form_submissions(form_id);
```

### FormAPIHandler Constructor Change
`FormAPIHandler.__init__()` must accept an optional `submission_storage: FormSubmissionStorage | None = None` parameter. When `None`, the submit_data endpoint stores nothing locally but still validates and forwards.

### Known Risks / Gotchas
- **Deep merge edge cases**: Arrays (sections, fields) are replaced wholesale in merge-patch — a client cannot add a single field without sending the entire sections array. This is a known RFC 7396 limitation and is acceptable for v1.
- **Concurrent edits**: `FormRegistry._lock` serializes access. Last-write-wins. Acceptable for v1.
- **Forward timeout**: `SubmissionForwarder` must use a reasonable timeout (30s default) to avoid blocking the response indefinitely.
- **navconfig dependency**: `navconfig` is used project-wide but is NOT a dependency of `parrot-formdesigner` package. The `AuthConfig.resolve()` method should handle `ImportError` gracefully and fall back to `os.environ.get()`.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `aiohttp` | existing | HTTP client for `SubmissionForwarder` |
| `asyncpg` | existing | `FormSubmissionStorage` table operations |
| `navconfig` | existing (optional) | Env variable resolution for auth credentials |
| `pydantic` | existing (v2) | New data models |

---

## 8. Open Questions

- [x] Should version bumping be automatic on every edit or caller-controlled? (Spec assumes automatic) — *Owner: Jesus Lara*: automatic
- [x] Should `form_submissions` table be in the same PostgreSQL schema as `form_schemas`? (Spec assumes yes) — *Owner: Jesus Lara*: yes
- [x] Should forwarding be synchronous (block until response) or fire-and-forget? (Spec assumes synchronous with timeout) — *Owner: Jesus Lara*: sync to know the response of backend.
- [x] Maximum payload size limit for submission data? (Spec does not impose one) — *Owner: Jesus Lara*: not impose one max size.

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — all tasks run sequentially in one worktree
- **Rationale**: Modules 1-2 (AuthConfig + SubmitAction extension) must land before Modules 3-6. Modules 5-6 both modify `handlers/api.py`. Sequential execution avoids merge conflicts and dependency issues.
- **Cross-feature dependencies**: None — no other in-flight specs modify `core/schema.py`, `handlers/api.py`, or `handlers/routes.py`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-06 | Jesus Lara | Initial draft from brainstorm |
