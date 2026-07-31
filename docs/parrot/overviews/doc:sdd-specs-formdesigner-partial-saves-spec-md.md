---
type: Wiki Overview
title: 'Feature Specification: FormDesigner Partial Saves'
id: doc:sdd-specs-formdesigner-partial-saves-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: When users fill out complex multi-section forms in the frontend, any browser
---

---
type: feature
base_branch: dev
---

# Feature Specification: FormDesigner Partial Saves

**Feature ID**: FEAT-186
**Date**: 2026-05-19
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Proposal**: `sdd/proposals/formdesigner-partial-saves.proposal.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

When users fill out complex multi-section forms in the frontend, any browser
crash, accidental navigation, or session interruption causes complete data loss.
Users must restart the entire form from scratch. For lengthy forms (20+ fields),
this is a significant UX pain point that leads to form abandonment.

The FormDesigner currently has no mechanism for persisting in-progress form
data. The existing `FormSubmissionStorage` only handles complete, validated
submissions -- there is no ephemeral layer for work-in-progress answers.

### Goals

- **G1**: Allow frontends to save partial form answers incrementally (one field
  at a time or in bulk) to a Redis-backed ephemeral store.
- **G2**: Provide session isolation -- each user session gets its own partial
  save namespace, preventing data leakage between users.
- **G3**: Automatic TTL expiration (1 hour default) enables crash recovery
  while preventing unbounded Redis growth.
- **G4**: New values for an already-cached field always override the cached
  value (last-write-wins).
- **G5**: Per-field validation on save provides real-time feedback to the
  frontend without requiring full form submission.
- **G6**: Optional server-side merge of cached partials into the final
  submission via `?merge_partials=true` on the submit endpoint.

### Non-Goals (explicitly out of scope)

- **Durable persistence**: Partial saves are ephemeral (Redis-only). No
  PostgreSQL fallback or backup. If Redis is unavailable, partial saves fail
  and the frontend must handle gracefully.
- **Multi-device sync**: Partial saves are scoped to a single session ID.
  Cross-device continuation is not supported.
- **Conflict resolution**: Last-write-wins only. No OT/CRDT-style merging.
- **Offline support**: Requires active backend connection.
- **Modification of existing FormCache**: The form schema cache is a separate
  concern and remains untouched.

---

## 2. Architectural Design

### Overview

A new `PartialSaveStore` service provides Redis-backed ephemeral storage for
partial form answers. It follows the same architectural patterns as the
existing `FormCache` (lazy `redis.asyncio` connection, `SETEX` with TTL,
`asyncio.Lock`, Pydantic serialization) but operates on a different key
namespace (`parrot:partial:`) and stores field-level answer data rather than
form schema objects.

Three new REST endpoints expose the service:
- `POST /api/v1/forms/{form_id}/partial` -- save partial answers
- `GET /api/v1/forms/{form_id}/partial` -- retrieve cached answers
- `DELETE /api/v1/forms/{form_id}/partial` -- clear cached answers

Each partial save validates submitted fields via `FormValidator.validate_field()`
and returns per-field errors immediately, enabling real-time validation UX.

The existing `submit_data()` endpoint gains an optional `?merge_partials=true`
query parameter. When set, the backend loads cached partials and merges them
under the submitted payload before validation (submitted values override cached).

### Component Diagram

```
Frontend
   │
   ├── POST /forms/{form_id}/partial ───→ FormAPIHandler.save_partial()
   │                                           │
   │                                           ├──→ PartialSaveStore.save()  ──→ Redis
   │                                           │       (SETEX with TTL)        (parrot:partial:{form_id}:{session_id})
   │                                           │
   │                                           └──→ FormValidator.validate_field()
   │                                                    (per-field real-time errors)
   │
   ├── GET /forms/{form_id}/partial ────→ FormAPIHandler.get_partial()
   │                                           │
   │                                           └──→ PartialSaveStore.get()   ──→ Redis
   │
   ├── DELETE /forms/{form_id}/partial ─→ FormAPIHandler.delete_partial()
   │                                           │
   │                                           └──→ PartialSaveStore.delete() ──→ Redis
   │
   └── POST /forms/{form_id}/data ──────→ FormAPIHandler.submit_data()
              (?merge_partials=true)            │
                                                ├──→ PartialSaveStore.get() (if merge)
                                                ├──→ merge cached + submitted
                                                ├──→ FormValidator.validate() (full)
                                                ├──→ FormSubmissionStorage.store()
                                                └──→ PartialSaveStore.delete() (cleanup)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FormCache` (services/cache.py) | pattern replication | Same Redis patterns, different key namespace |
| `FormAPIHandler` (api/handlers.py) | extended | New handler methods + constructor param |
| `FormValidator.validate_field()` (services/validators.py) | consumed | Per-field validation on partial save |
| `setup_form_api()` (api/routes.py) | extended | 3 new routes + new `partial_store` param |
| `navigator_auth` (`_wrap_auth`) | consumed | Auth on all new endpoints |
| `FormRegistry` (services/registry.py) | consumed | Load form schema to validate fields |

### Data Models

```python
# New: packages/parrot-formdesigner/src/parrot_formdesigner/core/partial.py

class PartialFormData(BaseModel):
    """Ephemeral partial form answer cache entry.

    Stored in Redis under key parrot:partial:{form_id}:{session_id}.
    """

    form_id: str
    session_id: str
    data: dict[str, Any]            # field_id -> value (sparse)
    field_errors: dict[str, list[str]]  # field_id -> [error_msg, ...]
    saved_at: datetime
    expires_at: datetime
```

### New Public Interfaces

```python
# New: packages/parrot-formdesigner/src/parrot_formdesigner/services/partial_saves.py

class PartialSaveStore:
    """Redis-backed ephemeral storage for partial form answers."""

    REDIS_KEY_PREFIX = "parrot:partial:"

    def __init__(
        self,
        ttl_seconds: int = 3600,
        redis_url: str | None = None,
    ) -> None: ...

    async def save(
        self,
        form_id: str,
        session_id: str,
        answers: dict[str, Any],
    ) -> PartialFormData:
        """Merge answers into cached partial and return the updated state.

        New values override existing cached values (last-write-wins).
        """
        ...

    async def get(
        self,
        form_id: str,
        session_id: str,
    ) -> PartialFormData | None:
        """Retrieve cached partial answers. Returns None if expired or absent."""
        ...

    async def delete(
        self,
        form_id: str,
        session_id: str,
    ) -> bool:
        """Remove cached partial answers. Returns True if key existed."""
        ...

    async def close(self) -> None:
        """Close the Redis connection if open."""
        ...
```

```python
# Extended: FormAPIHandler gains new methods

class FormAPIHandler:
    def __init__(
        self,
        registry: FormRegistry,
        client: AbstractClient | None = None,
        submission_storage: FormSubmissionStorage | None = None,
        forwarder: SubmissionForwarder | None = None,
        partial_store: PartialSaveStore | None = None,  # NEW
    ) -> None: ...

    async def save_partial(self, request: web.Request) -> web.Response:
        """POST /forms/{form_id}/partial — Save partial answers with validation."""
        ...

    async def get_partial(self, request: web.Request) -> web.Response:
        """GET /forms/{form_id}/partial — Retrieve cached partial answers."""
        ...

    async def delete_partial(self, request: web.Request) -> web.Response:
        """DELETE /forms/{form_id}/partial — Clear cached partial answers."""
        ...
```

### API Contracts

#### POST `/api/v1/forms/{form_id}/partial`

**Request body:**
```json
{
  "answers": {
    "field_id_1": "value1",
    "field_id_2": 42
  }
}
```

**Response (200):**
```json
{
  "form_id": "my-form",
  "session_id": "abc-123",
  "data": {
    "field_id_1": "value1",
    "field_id_2": 42,
    "field_id_3": "previously_cached"
  },
  "field_errors": {
    "field_id_2": ["Age must be at least 18"]
  },
  "saved_at": "2026-05-19T12:00:00Z",
  "expires_at": "2026-05-19T13:00:00Z"
}
```

**Error responses:**
- `400` — invalid JSON body
- `404` — form not found in registry
- `400` — session_id not available (missing auth session)
- `503` — Redis unavailable (partial_store not configured or Redis down)

#### GET `/api/v1/forms/{form_id}/partial`

**Response (200):**
```json
{
  "form_id": "my-form",
  "session_id": "abc-123",
  "data": { ... },
  "field_errors": { ... },
  "saved_at": "2026-05-19T12:00:00Z",
  "expires_at": "2026-05-19T13:00:00Z"
}
```

**Response (404):** No cached partial found for this form+session.

#### DELETE `/api/v1/forms/{form_id}/partial`

**Response (204):** Partial cleared (or did not exist).

#### POST `/api/v1/forms/{form_id}/data?merge_partials=true`

Existing submit endpoint. When `merge_partials=true`:
1. Load cached partials for this form+session
2. Merge: `merged = {**cached_data, **submitted_data}` (submitted wins)
3. Validate merged data via `FormValidator.validate()`
4. On successful submission, delete the cached partial
5. If no cached partial exists, proceed with submitted data only

---

## 3. Module Breakdown

### Module 1: PartialFormData Model
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/partial.py`
- **Responsibility**: Pydantic model for partial form data. Serializable to/from
  JSON for Redis storage.
- **Depends on**: `pydantic.BaseModel`

### Module 2: PartialSaveStore Service
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/partial_saves.py`
- **Responsibility**: Redis-backed ephemeral storage with TTL. Implements save
  (merge-on-write), get, delete, close. Follows FormCache patterns.
- **Depends on**: Module 1, `redis.asyncio`

### Module 3: Handler Methods
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
  (modify existing)
- **Responsibility**: `save_partial()`, `get_partial()`, `delete_partial()` handler
  methods on `FormAPIHandler`. Extract session_id, delegate to PartialSaveStore,
  run per-field validation, return responses.
- **Depends on**: Module 2, `FormValidator.validate_field()`, `FormRegistry`

### Module 4: Submit Merge Integration
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
  (modify existing `submit_data()`)
- **Responsibility**: Read `?merge_partials` query param. When true, load cached
  partials from PartialSaveStore, merge with submitted data, then proceed with
  existing validation/submit flow. Delete cached partial after successful submit.
- **Depends on**: Module 2, Module 3

### Module 5: Route Registration
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`
  (modify existing)
- **Responsibility**: Add `partial_store` parameter to `setup_form_api()`. Register
  3 new routes with `_wrap_auth()`.
- **Depends on**: Module 3

### Module 6: Unit & Integration Tests
- **Path**: `packages/parrot-formdesigner/tests/test_partial_saves.py`
- **Responsibility**: Test all partial save operations, merge behavior, TTL,
  session isolation, validation, and edge cases.
- **Depends on**: Modules 1-5

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_partial_save_store_save_single_field` | M2 | Save one field, verify stored |
| `test_partial_save_store_save_bulk` | M2 | Save multiple fields at once |
| `test_partial_save_store_merge_overwrite` | M2 | New values override cached values |
| `test_partial_save_store_get_existing` | M2 | Retrieve previously saved data |
| `test_partial_save_store_get_nonexistent` | M2 | Returns None when no data cached |
| `test_partial_save_store_delete` | M2 | Delete removes cached data |
| `test_partial_save_store_ttl_expiry` | M2 | Expired entries return None |
| `test_partial_save_store_session_isolation` | M2 | Different sessions have separate data |
| `test_partial_save_store_no_redis` | M2 | Graceful failure when Redis unavailable |
| `test_partial_form_data_serialization` | M1 | Pydantic model round-trip JSON |
| `test_save_partial_handler_single` | M3 | POST /partial with one field |
| `test_save_partial_handler_bulk` | M3 | POST /partial with multiple fields |
| `test_save_partial_validation_errors` | M3 | Returns field_errors for invalid values |
| `test_save_partial_form_not_found` | M3 | 404 when form not in registry |
| `test_save_partial_no_session` | M3 | 400 when session_id missing |
| `test_get_partial_handler` | M3 | GET /partial returns cached data |
| `test_get_partial_not_found` | M3 | 404 when nothing cached |
| `test_delete_partial_handler` | M3 | DELETE /partial returns 204 |
| `test_submit_merge_partials` | M4 | Submit with ?merge_partials=true merges data |
| `test_submit_merge_override` | M4 | Submitted values override cached |
| `test_submit_merge_cleanup` | M4 | Cached partial deleted after submit |
| `test_submit_no_merge_flag` | M4 | Default behavior unchanged |

### Integration Tests

| Test | Description |
|---|---|
| `test_partial_save_full_lifecycle` | Save fields incrementally, retrieve, submit with merge, verify cleanup |
| `test_partial_save_crash_recovery` | Save partial, simulate disconnect, retrieve within TTL window |
| `test_partial_save_concurrent_sessions` | Two sessions saving to same form, verify isolation |

### Test Fixtures

```python
@pytest.fixture
def partial_store(redis_url):
    return PartialSaveStore(ttl_seconds=60, redis_url=redis_url)

@pytest.fixture
def sample_form():
    return FormSchema(
        form_id="test-form",
        title="Test Form",
        sections=[FormSection(
            section_id="s1",
            fields=[
                FormField(field_id="name", field_type=FieldType.TEXT,
                          label="Name", required=True),
                FormField(field_id="age", field_type=FieldType.INTEGER,
                          label="Age", constraints=FieldConstraints(
                              min_value=18, max_value=120)),
                FormField(field_id="email", field_type=FieldType.EMAIL,
                          label="Email"),
            ],
        )],
    )
```

---

## 5. Acceptance Criteria

- [ ] `PartialSaveStore.save()` stores field answers in Redis with 1-hour TTL
- [ ] `PartialSaveStore.get()` retrieves cached answers (returns None if expired)
- [ ] `PartialSaveStore.delete()` removes cached answers
- [ ] Redis key format is `parrot:partial:{form_id}:{session_id}`
- [ ] New values for an existing field override the cached value (last-write-wins)
- [ ] Each partial save validates fields via `FormValidator.validate_field()` and
  returns per-field errors in the response
- [ ] POST `/api/v1/forms/{form_id}/partial` accepts `{"answers": {...}}` body
- [ ] GET `/api/v1/forms/{form_id}/partial` returns cached data or 404
- [ ] DELETE `/api/v1/forms/{form_id}/partial` clears cache and returns 204
- [ ] All new endpoints are protected by `_wrap_auth()` (navigator-auth)
- [ ] `submit_data()` with `?merge_partials=true` merges cached + submitted data
  (submitted values override cached) before validation
- [ ] Successful submission with merge deletes the cached partial
- [ ] Graceful degradation: if Redis is unavailable, partial save endpoints return
  503 with a clear error message (does not break other form operations)
- [ ] Session isolation: different session IDs produce independent caches
- [ ] All unit tests pass: `pytest packages/parrot-formdesigner/tests/test_partial_saves.py -v`
- [ ] No breaking changes to existing submit or validate endpoints
- [ ] No modification to existing `FormCache` service

---

## 6. Codebase Contract

### Verified Imports

```python
# Confirmed import paths (all relative within parrot_formdesigner package)
from ..core.schema import FormSchema, FormField, FormSection  # verified: core/schema.py:23,101,153
from ..core.types import FieldType                             # verified: core/types.py (FieldType enum)
from ..core.constraints import FieldConstraints                # verified: core/constraints.py
from ..services.registry import FormRegistry                   # verified: services/registry.py:134
from ..services.validators import FormValidator, ValidationResult  # verified: services/validators.py:91,77
from ..services.submissions import FormSubmission, FormSubmissionStorage  # verified: services/submissions.py:35,71
from ..services.auth_context import AuthContext                # verified: services/auth_context.py

# Redis (lazy import — same pattern as FormCache)
from redis.asyncio import Redis  # verified: services/cache.py:92

# Auth decorators (hard dependency)
from navigator_auth.decorators import is_authenticated, user_session  # verified: api/routes.py:34

# aiohttp
from aiohttp import web  # verified: api/handlers.py import
```

### Existing Class Signatures

```python
# services/cache.py — PATTERN TO REPLICATE
class FormCache:  # line 38
    REDIS_KEY_PREFIX = "parrot:form:"  # line 57
    def __init__(self, ttl_seconds: int = 3600, redis_url: str | None = None) -> None:  # line 59
    async def _get_redis(self) -> Any | None:  # line 80 (lazy double-checked locking)
    async def get(self, form_id: str) -> FormSchema | None:  # line 102
    async def set(self, form: FormSchema) -> None:  # line 136
    async def invalidate(self, form_id: str) -> None:  # line 160
    async def close(self) -> None:  # line 293

# api/handlers.py
class FormAPIHandler:  # line 33
    def __init__(
        self,
        registry: FormRegistry,
        client: "AbstractClient | None" = None,
        submission_storage: "FormSubmissionStorage | None" = None,
        forwarder: "SubmissionForwarder | None" = None,
    ) -> None:  # line 51
    async def submit_data(self, request: web.Request) -> web.Response:  # line 566
    async def validate(self, request: web.Request) -> web.Response:  # line 276

# services/validators.py
class ValidationResult(BaseModel):  # line 77
    is_valid: bool
    errors: dict[str, list[str]]
    sanitized_data: dict[str, Any]

class FormValidator:  # line 91
    async def validate(
        self, form: FormSchema, data: dict[str, Any],
        *, locale: str = "en", auth_context: AuthContext | None = None,
    ) -> ValidationResult:  # line 112
    async def validate_field(
        self, field: FormField, value: Any,
        *, all_data: dict[str, Any] | None = None,
        locale: str = "en", auth_context: AuthContext | None = None,
    ) -> list[str]:  # line 179

# services/registry.py
class FormRegistry:  # line 134
    async def get(self, form_id: str) -> FormSchema | None:  # (async, uses lock)
    async def on_startup(self, app: "web.Application") -> None:  # line 232
    async def on_shutdown(self, app: "web.Application") -> None:  # line 261

# api/routes.py
def _wrap_auth(handler: _Handler) -> _Handler:  # line 59
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
```

### Session ID Extraction Pattern

```python
# Verified at api/uploads.py:316-319
session_id: str | None = None
if "session" in request:
    _sid = request["session"].get("id")
    session_id = str(_sid) if _sid else None
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `PartialSaveStore` | Redis | `redis.asyncio.Redis.from_url()` | `services/cache.py:93` |
| `PartialSaveStore` | Pydantic serialization | `model_dump_json()` / `model_validate_json()` | `services/cache.py:247,262` |
| `FormAPIHandler.save_partial()` | `FormValidator.validate_field()` | method call | `services/validators.py:179` |
| `FormAPIHandler.save_partial()` | `FormRegistry.get()` | method call (load form for field lookup) | `services/registry.py:134` |
| `FormAPIHandler.submit_data()` | `PartialSaveStore.get()` | method call (when merge_partials=true) | NEW |
| `setup_form_api()` | `PartialSaveStore` | new `partial_store` kwarg | `api/routes.py:84` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot_formdesigner.services.partial_saves`~~ -- does not exist yet (to be created)
- ~~`parrot_formdesigner.core.partial`~~ -- does not exist yet (to be created)
- ~~`PartialSaveStore`~~ -- does not exist yet
- ~~`PartialFormData`~~ -- does not exist yet
- ~~`FormAPIHandler.save_partial()`~~ -- does not exist yet
- ~~`FormAPIHandler.get_partial()`~~ -- does not exist yet
- ~~`FormAPIHandler.delete_partial()`~~ -- does not exist yet
- ~~`FormCache.get_partial()`~~ -- FormCache has no partial-related methods
- ~~`FormSubmission.partial`~~ -- FormSubmission has no partial flag
- ~~`FormSubmissionStorage.store_partial()`~~ -- not a real method

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Redis lazy init**: Double-checked locking with `asyncio.Lock`, exactly as
  `FormCache._get_redis()` (cache.py:80-100). *Evidence*: F001
- **SETEX for TTL**: Use `redis.setex(key, ttl_secs, json_str)` like
  `FormCache._redis_set()` (cache.py:252-266). *Evidence*: F001
- **Pydantic serialization**: `model_dump_json()` for write, `model_validate_json()`
  for read. *Evidence*: F001
- **Handler DI**: New `partial_store` param on `FormAPIHandler.__init__()` with
  `None` default. Check `is not None` before use. *Evidence*: F004
- **Session extraction**: `request["session"]["id"]` pattern from
  uploads.py:316-319. *Evidence*: F006
- **Error handling**: Wrap Redis calls in try/except, log warnings, return
  graceful error responses. Never let Redis failures crash form operations.

### Known Risks / Gotchas

- **Redis unavailability**: If Redis is down, partial save endpoints return 503.
  Other form operations (CRUD, submit without merge) are unaffected.
  *Mitigation*: Partial store is optional (`None` default). Endpoints check
  and return 503 if not configured.

- **Nested field keys (GROUP/ARRAY)**: The `field_id` is flat (e.g., `"name"`,
  `"address"`), but GROUP fields have children with their own `field_id`.
  For partial saves, use flat `field_id` keys only. Nested GROUP/ARRAY data
  is stored as the value (e.g., `{"address": {"street": "...", "city": "..."}}`).
  *Evidence*: F003

- **Session ID absence**: If `request["session"]` is missing or has no `"id"`,
  the handler must return 400 with a clear error. This should not happen on
  `_wrap_auth()` routes but must be handled defensively.

- **TTL refresh**: Each `save()` call resets the TTL for the entire partial
  cache entry (not per-field). This is intentional -- any activity extends
  the recovery window.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `redis` (async) | `>=4.5` | Already used by `FormCache`. Lazy-imported. |

---

## 8. Open Questions

### Resolved (from proposal phase)

- [x] **Should the submit endpoint auto-merge cached partials?** --
  *Resolved in proposal*: Both supported. A query param `?merge_partials=true`
  controls whether backend merges. Default: `false` (frontend responsibility).

- [x] **Should partial saves include per-field validation?** --
  *Resolved in proposal*: Validate on save. Each partial save validates fields

…(truncated)…
