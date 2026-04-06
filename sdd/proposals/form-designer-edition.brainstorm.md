# Brainstorm: Form Designer Edition (Edit API)

**Date**: 2026-04-06
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

Once a form is created in AI-Parrot's form designer (via natural language, YAML, database import, or Pydantic extraction), there is no API to edit it. Developers and end-users consuming the API cannot:

- Rename field keys (`field_id`) in the result dictionary (column/field names)
- Change the form title, description, or section structure
- Modify the submit destination (where form data goes after submission)
- Configure HTTP method, URL, and authentication for result forwarding
- Receive and store form submission data

The only workaround is to recreate the form from scratch, losing the `form_id` or requiring manual coordination. This blocks any UI-based form editing workflow and limits the API's usefulness for developers building on top of the form system.

**Who is affected:** Developers consuming the form REST API, and end-users of any future form editor UI that calls these APIs.

## Constraints & Requirements

- Must be pure REST API (no LLM tool, no UI component in this scope)
- PATCH for partial updates, PUT for full replacement
- Auth credentials for submit destinations must reference environment variables via `navconfig.config.get()` — never store raw secrets in the form schema
- Form submission data must be stored locally AND forwarded to the configured `SubmitAction` endpoint
- `FormValidator.check_schema()` must run before any edit is persisted
- Edits must work on all forms in `FormRegistry`, whether persisted or in-memory only
- Version string is updated on edit, but previous versions are NOT retained in this scope
- Field key renaming is only relevant for forms without collected data (no migration needed)
- Must integrate with existing `navigator-auth` protection pattern

---

## Options Explored

### Option A: Extend FormAPIHandler with PATCH/PUT + Submission Endpoint

Add `PUT` and `PATCH` endpoints directly to the existing `FormAPIHandler` class, plus a new `POST .../data` endpoint for submission storage and forwarding. Introduce an `AuthConfig` model on `SubmitAction` and a `FormSubmissionStorage` service for local data persistence.

**Flow:**
- `PUT /api/v1/forms/{form_id}` — full replacement with a new `FormSchema` body
- `PATCH /api/v1/forms/{form_id}` — JSON merge-patch (RFC 7396) for partial updates
- `POST /api/v1/forms/{form_id}/data` — validate, store locally, forward to `SubmitAction`

The PATCH applies a deep merge of the incoming partial JSON onto the existing `FormSchema.model_dump()`, then validates the result via `FormSchema.model_validate()` + `FormValidator.check_schema()`.

Auth credentials are stored as env var references (e.g., `{"type": "bearer", "token_env": "MY_API_TOKEN"}`) and resolved at forwarding time via `navconfig.config.get()`.

Pros:
- Minimal new abstractions — extends existing handler and models
- JSON merge-patch is a well-understood standard (RFC 7396)
- Single class remains the authority for all form API operations
- Straightforward to test — same patterns as existing endpoints

Cons:
- `FormAPIHandler` grows larger (already 8 methods, adds 3-4 more)
- Deep merge logic for nested sections/fields needs careful implementation
- No undo/rollback capability (acceptable per scope)

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | HTTP client for forwarding submissions | Already a dependency |
| `navconfig` | Env variable resolution for auth credentials | Already used in project |
| `asyncpg` | Submission data storage | Already a dependency |

**Existing Code to Reuse:**
- `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py` — FormAPIHandler (extend)
- `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py` — setup_form_routes (add new routes)
- `packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py` — SubmitAction (extend with auth)
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py` — FormRegistry.register(overwrite=True)
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py` — PostgresFormStorage (persist edits)
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/validators.py` — FormValidator.check_schema()

---

### Option B: Separate FormEditorHandler + Operation-Based Mutations

Create a new `FormEditorHandler` class with fine-grained, operation-based endpoints:
- `PATCH .../title` — update title
- `PATCH .../submit` — update submit action
- `POST .../sections/{section_id}/fields` — add field
- `DELETE .../fields/{field_id}` — remove field
- `PATCH .../fields/{field_id}` — update single field

Each operation is its own endpoint with a focused schema.

Pros:
- Very precise — each operation is self-documenting
- Easier to validate individual operations in isolation
- Separation of concerns (read API vs edit API)

Cons:
- Many endpoints to implement and maintain (~10+ routes)
- Clients need multiple calls for complex edits (rename 3 fields = 3 requests)
- Higher API surface area = more documentation, more test cases
- No standard for this pattern (custom protocol)
- Reordering sections/fields requires additional operation types

**Effort:** High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | HTTP server + client | Already a dependency |
| `navconfig` | Env variable resolution | Already used |

**Existing Code to Reuse:**
- Same as Option A, but with a new handler class instead of extending

---

### Option C: JSON Patch (RFC 6902) Operations Endpoint

Expose a single `PATCH /api/v1/forms/{form_id}` endpoint that accepts JSON Patch (RFC 6902) operations — an array of `{op, path, value}` objects:

```json
[
  {"op": "replace", "path": "/title", "value": "New Title"},
  {"op": "replace", "path": "/sections/0/fields/1/field_id", "value": "new_key"},
  {"op": "add", "path": "/sections/0/fields/-", "value": {...}}
]
```

Pros:
- Industry standard (RFC 6902) — well-known by API consumers
- Single endpoint handles all mutation types
- Atomic: all operations succeed or all fail
- Libraries exist (`jsonpatch` PyPI package)

Cons:
- Path-based addressing (`/sections/0/fields/1`) is fragile — depends on array indices
- Harder for UI builders to construct correct patch documents
- Requires knowing the full structure to build paths
- `jsonpatch` library applies patches on raw dicts, not Pydantic models — need serialize/patch/revalidate cycle
- Less intuitive than merge-patch for simple cases like "update the title"

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `jsonpatch` | RFC 6902 implementation | v1.33, mature, well-maintained |
| `aiohttp` | HTTP server + client | Already a dependency |

**Existing Code to Reuse:**
- Same core files as Option A

---

## Recommendation

**Option A** is recommended because:

1. **Simplicity for consumers**: JSON merge-patch (PATCH) and full replacement (PUT) are the most intuitive patterns for developers. A UI can simply send the modified form or the changed fields — no need to construct patch operations or call 10 different endpoints.

2. **Minimal new surface area**: Adds 3-4 methods to an existing handler + 2-3 new routes. No new handler classes or external libraries needed.

3. **Aligns with existing patterns**: `FormRegistry.register(overwrite=True)` already supports the core operation. The edit endpoints are essentially "validate + re-register + optionally persist."

4. **Tradeoff accepted**: The handler grows larger, but the methods are self-contained and follow the same pattern as existing endpoints. If it gets unwieldy later, extraction to a mixin or separate handler is straightforward.

Option B was rejected because the API surface explosion (10+ endpoints) is disproportionate for the problem. Option C was rejected because RFC 6902 path-based addressing is fragile for nested form schemas and unintuitive for most consumers.

---

## Feature Description

### User-Facing Behavior

**Editing a form (developer via API):**

1. `GET /api/v1/forms/{form_id}` — retrieve the current form definition
2. Modify the desired fields in the JSON
3. `PUT /api/v1/forms/{form_id}` — replace entirely, or
   `PATCH /api/v1/forms/{form_id}` — send only changed fields (merge-patch)
4. Response: updated `FormSchema` JSON with new version, or 422 with validation errors

**Configuring the submit destination:**

The `SubmitAction` model gains an `auth` field supporting pluggable auth strategies:

```json
{
  "submit": {
    "action_type": "endpoint",
    "action_ref": "https://api.example.com/intake",
    "method": "POST",
    "auth": {
      "type": "bearer",
      "token_env": "EXAMPLE_API_TOKEN"
    }
  }
}
```

Auth types supported in v1:
- `bearer` — resolves `token_env` to a Bearer token via `navconfig.config.get()`
- `api_key` — resolves `key_env` and sends as a configurable header (default `X-API-Key`)
- `none` — no authentication (default, backward-compatible)

**Submitting form data:**

`POST /api/v1/forms/{form_id}/data` with JSON body:
1. Validates data against the form schema (existing `FormValidator`)
2. Stores submission locally in a `form_submissions` table
3. If `SubmitAction` is configured with `action_type: "endpoint"`, forwards the validated data to the configured URL with the resolved auth credentials
4. Returns: `{submission_id, is_valid, forwarded: true/false, forward_status: 200}`

### Internal Behavior

**Edit flow (PATCH):**
1. Load existing `FormSchema` from `FormRegistry`
2. Serialize to dict via `model_dump()`
3. Deep-merge incoming partial JSON onto existing dict
4. Validate merged result via `FormSchema.model_validate()` (structural)
5. Run `FormValidator.check_schema()` (circular dependency check)
6. Bump version string (e.g., "1.0" → "1.1")
7. Re-register in `FormRegistry` with `overwrite=True`
8. If `FormRegistry` has a storage backend, persist via `FormStorage.save()`
9. Return updated `FormSchema`

**Edit flow (PUT):**
Same as PATCH but skips step 2-3 (no merge — full replacement). The incoming body must be a complete `FormSchema`. The `form_id` in the URL must match the body.

**Submission flow:**
1. Load `FormSchema` from registry
2. Validate submission data via `FormValidator.validate()`
3. Store in `form_submissions` table (asyncpg)
4. If `submit.action_type == "endpoint"`:
   a. Resolve auth credentials from env via `navconfig.config.get()`
   b. Build HTTP request with resolved auth headers
   c. Forward validated data via `aiohttp.ClientSession`
   d. Record forward status
5. Return result with submission_id, validation status, and forward status

### Edge Cases & Error Handling

- **Form not found**: 404 for any operation on a non-existent `form_id`
- **Validation failure on edit**: 422 with `FormValidator` errors — edit is rejected, original form unchanged
- **form_id mismatch on PUT**: 400 if URL `form_id` differs from body `form_id`
- **Env variable not found**: If `navconfig.config.get(token_env)` returns None, the forward fails with a clear error in the response (does not block local storage)
- **Forward endpoint unreachable**: Store locally, return `forwarded: false` with error details — data is not lost
- **Concurrent edits**: `FormRegistry._lock` (asyncio.Lock) serializes access. Last-write-wins semantics (acceptable for v1)
- **PATCH with empty body**: 400 — nothing to merge
- **Renaming field_id in PATCH**: Works via merge — the caller sends the full sections array with updated field_ids. No partial field rename (you replace the field definition).

---

## Capabilities

### New Capabilities
- `form-edit-api`: PUT and PATCH endpoints for modifying registered forms
- `form-submit-data`: Endpoint for receiving, storing, and forwarding form submissions
- `submit-action-auth`: Pluggable auth configuration on SubmitAction (bearer, api-key)

### Modified Capabilities
- `form-schema`: SubmitAction model extended with `auth: AuthConfig | None`
- `form-api-routes`: New routes added to `setup_form_routes()`
- `form-storage`: PostgresFormStorage used for persisting edits (no schema changes needed — existing UPSERT handles it)

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `core/schema.py` — `SubmitAction` | extends | Add `auth: AuthConfig \| None` field |
| `core/schema.py` — new `AuthConfig` | new model | Discriminated union: BearerAuth, ApiKeyAuth, NoAuth |
| `handlers/api.py` — `FormAPIHandler` | extends | Add `update_form`, `patch_form`, `submit_data` methods |
| `handlers/routes.py` — `setup_form_routes` | extends | Add PUT, PATCH, POST data routes |
| `services/registry.py` — `FormRegistry` | no change | Uses existing `register(overwrite=True)` |
| `services/storage.py` — `PostgresFormStorage` | no change | Existing UPSERT handles re-saves |
| `services/validators.py` — `FormValidator` | no change | Existing `check_schema()` and `validate()` used as-is |
| New: `services/submissions.py` | new module | `FormSubmissionStorage` for the `form_submissions` table |
| New: `services/forwarder.py` | new module | `SubmissionForwarder` — HTTP client for forwarding data with auth |

---

## Code Context

### User-Provided Code
_No code snippets provided by the user._

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py:89
class SubmitAction(BaseModel):
    action_type: Literal["tool_call", "endpoint", "event", "callback"]  # line 99
    action_ref: str  # line 100
    method: str = "POST"  # line 101
    confirm_message: LocalizedString | None = None  # line 102

# From packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py:105
class FormSchema(BaseModel):
    form_id: str  # line 122
    version: str = "1.0"  # line 123
    title: LocalizedString  # line 124
    description: LocalizedString | None = None  # line 125
    sections: list[FormSection]  # line 126
    submit: SubmitAction | None = None  # line 127
    cancel_allowed: bool = True  # line 128
    meta: dict[str, Any] | None = None  # line 129

# From packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py:94
class FormRegistry:
    def __init__(self, storage: FormStorage | None = None) -> None  # line 111
    async def register(self, form: FormSchema, *, persist: bool = False, overwrite: bool = True) -> None  # line 124
    async def get(self, form_id: str) -> FormSchema | None  # line 192
    async def contains(self, form_id: str) -> bool  # line 222
    # _storage: FormStorage | None — line 119
    # _lock: asyncio.Lock — line 118

# From packages/parrot-formdesigner/src/parrot/formdesigner/services/validators.py:66
class FormValidator:
    def check_schema(self, form: FormSchema) -> list[str]  # line 446
    async def validate(self, form: FormSchema, data: dict[str, Any], *, locale: str = "en") -> ValidationResult  # line 87

# From packages/parrot-formdesigner/src/parrot/formdesigner/services/validators.py:52
class ValidationResult(BaseModel):
    is_valid: bool
    errors: dict[str, list[str]]
    sanitized_data: dict[str, Any]

# From packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:29
class FormAPIHandler:
    def __init__(self, registry: FormRegistry, client: "AbstractClient | None" = None) -> None  # line 45
    # self.registry: FormRegistry — line 50
    # self.validator: FormValidator — line 54

# From packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py:39
class PostgresFormStorage(FormStorage):
    UPSERT_SQL = "INSERT ... ON CONFLICT (form_id, version) DO UPDATE ..."  # line 72
    async def save(self, form: FormSchema, style: StyleSchema | None = None, *, created_by: str | None = None) -> str  # line 124

# From packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py:80
def setup_form_routes(app, *, registry=None, client=None, prefix="", protect_pages=True) -> None  # line 80
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.formdesigner.core.schema import FormSchema, SubmitAction, FormField, FormSection  # core/schema.py
from parrot.formdesigner.services.registry import FormRegistry, FormStorage  # services/registry.py
from parrot.formdesigner.services.storage import PostgresFormStorage  # services/storage.py
from parrot.formdesigner.services.validators import FormValidator, ValidationResult  # services/validators.py
from parrot.formdesigner.handlers.api import FormAPIHandler  # handlers/api.py
from parrot.formdesigner.handlers.routes import setup_form_routes  # handlers/routes.py
from navconfig import config  # app.py:2 — used for env variable resolution
```

#### Key Attributes & Constants
- `FormRegistry._storage` → `FormStorage | None` (services/registry.py:119)
- `FormRegistry._lock` → `asyncio.Lock` (services/registry.py:118)
- `FormAPIHandler.registry` → `FormRegistry` (handlers/api.py:50)
- `FormAPIHandler.validator` → `FormValidator` (handlers/api.py:54)
- `PostgresFormStorage.UPSERT_SQL` — handles insert-or-update by `(form_id, version)` (services/storage.py:72)

### Does NOT Exist (Anti-Hallucination)
- ~~`FormRegistry.update()`~~ — no update method exists; use `register(overwrite=True)`
- ~~`FormAPIHandler.update_form()`~~ — no edit/update endpoint exists yet
- ~~`FormAPIHandler.patch_form()`~~ — no PATCH endpoint exists yet
- ~~`SubmitAction.auth`~~ — no auth configuration field exists on SubmitAction
- ~~`form_submissions` table~~ — no submission storage table exists
- ~~`FormSubmissionStorage`~~ — no submission storage service exists
- ~~`SubmissionForwarder`~~ — no forwarding service exists
- ~~`AuthConfig`~~ — no auth config model exists

---

## Open Questions

- [ ] Should version bumping be automatic (1.0 → 1.1 on every edit) or caller-controlled? — *Owner: Jesus Lara*
- [ ] Should `form_submissions` table be in the same schema as `form_schemas` or separate? — *Owner: Jesus Lara*
- [ ] Should forwarding be synchronous (wait for response) or fire-and-forget with async status tracking? — *Owner: Jesus Lara*
- [ ] Should there be a `GET /api/v1/forms/{form_id}/data` to retrieve stored submissions? — *Owner: Jesus Lara*
- [ ] Maximum payload size for submission data forwarding? — *Owner: Jesus Lara*

---

## Parallelism Assessment

- **Internal parallelism**: Yes — three independent workstreams:
  1. **Auth model** (`AuthConfig` on `SubmitAction`) — pure model change, no handler code
  2. **Edit endpoints** (PUT/PATCH on `FormAPIHandler`) — depends on auth model only for SubmitAction edits
  3. **Submission endpoint** (`POST .../data` + `FormSubmissionStorage` + `SubmissionForwarder`) — depends on auth model for forwarding

  Workstreams 2 and 3 share a dependency on workstream 1 (auth model), but are independent of each other after that.

- **Cross-feature independence**: No conflicts with in-flight specs. The changes touch `core/schema.py` (adding a field to `SubmitAction`) and `handlers/api.py` (new methods) — neither is being modified by other features.

- **Recommended isolation**: `per-spec` — all tasks run sequentially in one worktree. The auth model dependency makes full parallelism impractical, and the total scope is medium (not large enough to justify multiple worktrees).

- **Rationale**: The three workstreams have a shared dependency (AuthConfig model) that must land first. After that, edit and submission endpoints could theoretically run in parallel, but the shared handler file (`api.py`) would cause merge conflicts. Sequential execution in one worktree is simpler and safer.
