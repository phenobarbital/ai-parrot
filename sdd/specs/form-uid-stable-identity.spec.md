---
type: feature
base_branch: dev
---

# Feature Specification: Stable UUID-Based Form Identity (form_uid)

**Feature ID**: FEAT-389
**Date**: 2026-07-30
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.next

---

## 1. Motivation & Business Requirements

### Problem Statement

`form_id` is a mutable slug derived from the form title (e.g. `untitled-form`,
`customer-feedback`). It serves as the sole identity for forms across URLs,
the in-memory registry, the database, submissions, and blob storage.

This causes three concrete problems:

1. **Non-idempotent URLs** — `PATCH /api/v1/forms/untitled-form/operations`
   breaks if the form is renamed. The URL for a form is not stable.
2. **No stable reference** — external systems (submissions, blobs, integrations)
   that store `form_id` lose their link when the slug changes.
3. **Wasted DB UUID** — the `form_schemas` table already has
   `id UUID PRIMARY KEY DEFAULT gen_random_uuid()` but it is never exposed to
   the application layer.

### Goals
- Introduce `form_uid` (UUID4, auto-generated, immutable) as the primary identity
  for all URL routing, registry keys, storage lookups, and cross-system references.
- Keep `form_id` as a human-readable slug for display and search — never as a
  primary key.
- Add `POST /api/v1/forms/blank` for creating empty forms without LLM.
- Migrate existing data by promoting the existing DB UUID (`id`) to `form_uid`.

### Non-Goals (explicitly out of scope)
- Changing FormField, FormSection, or FormSubsection — they have no `form_id`
  back-reference.
- Modifying the question bank — no `form_id` column.
- FEAT-388 HTTP handler update for structured input — separate concern.
- Versioning semantics — `form_uid + version` replaces `form_id + version` as
  composite key, but versioning behavior is unchanged.
- Backwards-compatible slug-based routing or deprecation period — clean cut
  approved; no external clients depend on slug-based URLs.

---

## 2. Architectural Design

### Overview

Add `form_uid: str` (UUID4, auto-generated, immutable) to `FormSchema` as the
primary identity. Reindex `FormRegistry` on `form_uid` with a secondary slug
index. Change all API routes from `{form_id}` to `{form_uid}`. Update
PostgreSQL storage to use `form_uid` as the uniqueness key. Add a blank form
creation endpoint.

### Component Diagram
```
FormSchema (form_uid: UUID, form_id: slug)
     │
     ├──→ FormRegistry._forms[tenant][form_uid]
     │         │
     │         └──→ FormRegistry._slug_index[tenant][form_id] → form_uid
     │
     ├──→ API Routes: /api/v1/forms/{form_uid}/...
     │         │
     │         └──→ UUID validation helper (400 if invalid)
     │
     ├──→ PostgresFormStorage: UNIQUE(form_uid, version)
     │
     ├──→ FormSubmission.form_uid (stable FK)
     │
     └──→ BlobStorage keys: {prefix}{form_uid}/{field_id}/{blob_uuid}
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FormSchema` | extends | Add `form_uid` field with `default_factory=uuid4` |
| `FormRegistry` | modifies | Reindex primary dict on `form_uid`; add `_slug_index` and `get_by_slug()` |
| `FormAPIHandler` | modifies | All handlers: `match_info["form_id"]` → `match_info["form_uid"]`; add blank form handler |
| `setup_form_api()` | modifies | All route paths: `{form_id}` → `{form_uid}`; add `/forms/blank` route |
| `handle_operations()` | modifies | Path param extraction change |
| `PostgresFormStorage` | modifies | DDL migration, SQL queries use `form_uid` |
| `FormSubmission` | extends | Add `form_uid` field |
| `FormSubmissionStorage` | modifies | DDL migration, INSERT includes `form_uid` |
| `BlobMetadata` | extends | Add `form_uid` field |
| `_ManagerBackedBlobStorage._build_key()` | modifies | Key pattern uses `form_uid` |
| `CreateFormTool` | modifies | Generate/inject `form_uid`; rename `refine_form_id` → `refine_form_uid` |
| `CreateFormInput` | modifies | Add `form_uid` field; rename `refine_form_id` → `refine_form_uid` |
| UI routes | modifies | All paths: `{form_id}` → `{form_uid}` |

### Data Models

```python
class FormSchema(BaseModel):
    form_uid: str = Field(default_factory=lambda: str(uuid.uuid4()))
    form_id: str          # slug, mutable, human-readable
    version: str = "1.0"
    title: LocalizedString
    # ... rest unchanged

class FormSubmission(BaseModel):
    submission_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    form_uid: str         # NEW — stable identity
    form_id: str          # kept for human-readable queries
    form_version: str
    # ... rest unchanged

class BlobMetadata(BaseModel):
    form_uid: str         # NEW — used in key construction
    form_id: str          # kept for backwards compat in metadata
    field_id: str
    # ... rest unchanged
```

### New Public Interfaces

```python
# FormRegistry — new methods
class FormRegistry:
    async def get(self, form_uid: str, *, tenant: str | None = None) -> FormSchema | None:
        """Lookup by form_uid (primary key)."""

    async def get_by_slug(self, form_id: str, *, tenant: str | None = None) -> FormSchema | None:
        """Lookup by form_id slug (secondary index)."""

    async def list_form_uids(self, *, tenant: str | None = None) -> list[str]:
        """List all form_uids for a tenant."""

# UUID validation helper
def extract_form_uid(request: web.Request) -> str:
    """Extract and validate form_uid from path. Raises HTTPBadRequest if invalid UUID."""

# Blank form handler
class FormAPIHandler:
    async def create_blank_form(self, request: web.Request) -> web.Response:
        """Create an empty form without LLM. Requires 'title' in body."""
```

---

## 3. Module Breakdown

### Module 1: FormSchema — Add form_uid field
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py`
- **Responsibility**: Add `form_uid` field to `FormSchema` with UUID4 default factory.
- **Depends on**: none

### Module 2: FormRegistry — Reindex on form_uid
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py`
- **Responsibility**: Change primary index to `form_uid`, add `_slug_index`,
  implement `get_by_slug()` and `list_form_uids()`. Update `register()`,
  `get()`, `unregister()`, `contains()`, `clone_form()`.
- **Depends on**: Module 1

### Module 3: PostgresFormStorage — DDL migration and query updates
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py`
- **Responsibility**: Add `form_uid` column to DDL, change UNIQUE constraint to
  `(form_uid, version)`, update all SQL queries to use `form_uid`. Add index
  on `form_id` for slug search. Migration populates `form_uid` from existing `id`.
- **Depends on**: Module 1

### Module 4: API Routes and Handlers — Path param and UUID validation
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`,
  `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
- **Responsibility**: Rename `{form_id}` to `{form_uid}` in all route paths.
  Change all `request.match_info["form_id"]` to use `form_uid`. Add UUID
  validation helper. Add blank form endpoint (`POST /forms/blank`) and handler.
  Add `?slug=` query param support on list endpoint.
- **Depends on**: Module 2

### Module 5: Operations endpoint — Path param update
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/operations.py`
- **Responsibility**: Update `handle_operations()` to extract `form_uid` from
  path and lookup by UUID.
- **Depends on**: Module 2

### Module 6: CreateFormTool — form_uid generation and injection
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py`
- **Responsibility**: Add `form_uid` to `CreateFormInput`. Update `_execute()` and
  `_generate_with_retry()` to generate/inject `form_uid`. Rename `refine_form_id`
  to `refine_form_uid`. Update `ToolResult.metadata` to return `form_uid`.
- **Depends on**: Module 1, Module 2

### Module 7: Submissions — Add form_uid field and storage
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py`
- **Responsibility**: Add `form_uid` to `FormSubmission` model and `form_data`
  DDL. Update INSERT to include `form_uid`. Add index on `form_uid`.
- **Depends on**: Module 1

### Module 8: BlobStorage — Key pattern update
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/blob_storage.py`
- **Responsibility**: Add `form_uid` to `BlobMetadata`. Update `_build_key()`
  to use `form_uid` in key construction.
- **Depends on**: Module 1

### Module 9: UI Routes — Path param update
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/ui/routes.py`
- **Responsibility**: Rename `{form_id}` to `{form_uid}` in all UI route paths.
  Update UI page handlers to extract `form_uid`.
- **Depends on**: Module 2

### Module 10: Tests — Update existing and add new
- **Path**: `packages/parrot-formdesigner/tests/`
- **Responsibility**: Update all test helpers/fixtures to include `form_uid`.
  Update API test URLs from `/{form_id}` to `/{form_uid}`. Add new tests
  for: blank form creation, slug search, UUID validation (400 on invalid),
  form rename stability, registry dual-index, storage migration integrity.
- **Depends on**: Module 1–9

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_form_schema_form_uid_auto_generated` | Module 1 | FormSchema auto-generates UUID4 for `form_uid` |
| `test_form_schema_form_uid_immutable_on_rename` | Module 1 | Changing `form_id` does not change `form_uid` |
| `test_registry_index_by_form_uid` | Module 2 | `register()` stores under `form_uid` key |
| `test_registry_get_by_uid` | Module 2 | `get(form_uid)` returns correct form |
| `test_registry_get_by_slug` | Module 2 | `get_by_slug(form_id)` resolves via slug index |
| `test_registry_slug_update` | Module 2 | Re-registering with changed `form_id` updates slug index |
| `test_registry_clone_new_uid` | Module 2 | `clone_form()` generates new `form_uid` |
| `test_registry_unregister_cleans_both_indexes` | Module 2 | `unregister()` removes from `_forms` and `_slug_index` |
| `test_storage_upsert_by_form_uid` | Module 3 | UPSERT uses `(form_uid, version)` conflict key |
| `test_storage_load_by_form_uid` | Module 3 | `load(form_uid)` returns correct form |
| `test_storage_list_distinct_on_form_uid` | Module 3 | `list_forms()` returns one per `form_uid` |
| `test_create_tool_generates_form_uid` | Module 6 | `CreateFormTool._execute()` auto-generates `form_uid` |
| `test_create_tool_refine_by_uid` | Module 6 | Refinement looks up existing form by `form_uid` |
| `test_submission_stores_form_uid` | Module 7 | `FormSubmission` includes `form_uid` in saved data |
| `test_blob_key_uses_form_uid` | Module 8 | `_build_key()` uses `form_uid` in path |

### Integration Tests

| Test | Description |
|---|---|
| `test_create_blank_form_returns_uid` | `POST /forms/blank` with title returns valid `form_uid` |
| `test_slug_search_query_param` | `GET /forms?slug=my-form` returns form by slug |
| `test_invalid_uuid_returns_400` | `GET /forms/not-a-uuid` returns 400 |
| `test_rename_form_stable_url` | Change `form_id` via PATCH, same `form_uid` URL still works |
| `test_full_lifecycle_with_uid` | Create → edit → submit → retrieve, all by `form_uid` |
| `test_clone_gets_new_uid` | Clone via API returns new `form_uid`, original unchanged |

### Test Data / Fixtures

```python
import uuid

@pytest.fixture
def sample_form_uid():
    return str(uuid.uuid4())

@pytest.fixture
def sample_form(sample_form_uid):
    return FormSchema(
        form_uid=sample_form_uid,
        form_id="test-form",
        title="Test Form",
        sections=[FormSection(section_id="s1", title="Section 1", fields=[])],
    )
```

---

## 5. Acceptance Criteria

- [ ] `FormSchema` has `form_uid: str` field with UUID4 auto-generation
- [ ] `FormRegistry` indexes by `form_uid` as primary key
- [ ] `FormRegistry.get_by_slug()` resolves `form_id` → `form_uid` → form
- [ ] All API routes use `{form_uid}` path parameter (not `{form_id}`)
- [ ] Invalid UUID in path returns HTTP 400
- [ ] `POST /api/v1/forms/blank` creates empty form without LLM, returns `form_uid`
- [ ] `GET /api/v1/forms?slug=<slug>` searches by slug
- [ ] `PostgresFormStorage` uses `UNIQUE(form_uid, version)` constraint
- [ ] `FormSubmission` includes `form_uid` field
- [ ] `BlobStorage` keys use `form_uid` in path
- [ ] Renaming a form (`form_id` change) does not change its `form_uid` or break its URL
- [ ] `CreateFormTool` generates and injects `form_uid`
- [ ] All existing tests updated and passing
- [ ] New tests for blank form, slug search, UUID validation, rename stability
- [ ] SQL migration scripts populate `form_uid` from existing DB `id` UUID

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
from parrot_formdesigner.core.schema import FormSchema       # verified: core/__init__.py re-exports
from parrot_formdesigner.core.schema import FormField         # verified: core/__init__.py re-exports
from parrot_formdesigner.core.schema import FormSection       # verified: core/__init__.py re-exports
from parrot_formdesigner.services.registry import FormRegistry  # verified: services/registry.py:146
from parrot_formdesigner.services.storage import PostgresFormStorage  # verified: services/storage.py:63
from parrot_formdesigner.services.submissions import FormSubmission  # verified: services/submissions.py:50
from parrot_formdesigner.services.blob_storage import BlobMetadata  # verified: services/blob_storage.py:55
from parrot_formdesigner.services.blob_storage import AbstractBlobStorage  # verified: services/blob_storage.py:100
from parrot_formdesigner.tools.create_form import CreateFormTool  # verified: tools/create_form.py:259
from parrot_formdesigner.tools.create_form import CreateFormInput  # verified: tools/create_form.py:223
from parrot_formdesigner.api.handlers import FormAPIHandler  # verified: api/handlers.py:46
from parrot_formdesigner.api.routes import setup_form_api  # verified: api/routes.py:94
from parrot_formdesigner.api.operations import handle_operations  # verified: api/operations.py:358
```

### Existing Class Signatures

```python
# core/schema.py
class FormSchema(BaseModel):                    # line 267
    form_id: str                                # line 305
    version: str = "1.0"                        # line 306
    title: LocalizedString                      # line 307
    description: LocalizedString | None = None  # line 308
    sections: list[FormSection]                 # line 309
    submit: SubmitAction | None = None          # line 310
    cancel_allowed: bool = True                 # line 311
    meta: dict[str, Any] | None = None          # line 312
    created_at: datetime | None = None          # line 313
    tenant: str | None = None                   # line 314
    metadata: list[FormMetadataField] | None = None  # line 315
    events: FormEventsConfig | None = None      # line 316
    form_type: FormType = FormType.SIMPLE       # line 318
    product_bindings: list[str] | None = None   # line 319
    published_version: str | None = None        # line 320
    is_public: bool = False                     # line 322
    def iter_all_fields(self) -> Iterator[FormField]:  # line 324
    @model_validator(mode="after")
    def _validate_metadata(self) -> "FormSchema":  # line 329

# services/registry.py
class FormRegistry:                             # line 146
    def __init__(self, storage: FormStorage | None = None, *, app=None,
                 default_tenant="navigator", require_tenant=True) -> None:  # line 175
    # Internal: self._forms: dict[str, dict[str, FormSchema]] = {}  # line 201
    def _resolve_tenant(self, tenant, form=None) -> str:  # line 234
    async def register(self, form, *, persist=False, overwrite=True, tenant=None) -> None:  # line 265
    async def unregister(self, form_id: str, *, tenant=None) -> bool:  # line 465
    async def clone_form(self, source_form_id, new_form_id, patch=None, *,
                         persist=True, tenant=None) -> FormSchema:  # line 512
    async def get(self, form_id: str, *, tenant=None) -> FormSchema | None:  # line 623
    async def list_forms(self, *, tenant=None) -> list[FormSchema]:  # line 639
    async def list_form_ids(self, *, tenant=None) -> list[str]:  # line 655
    async def contains(self, form_id: str, *, tenant=None) -> bool:  # line 668

# services/storage.py
class PostgresFormStorage(FormStorage):         # line 63
    def __init__(self, *, pool=None, dsn=None, schema=DEFAULT_SCHEMA,
                 table_name=DEFAULT_TABLE, tenant=None, **kw) -> None:  # line 96
    def _create_table_sql(self, tenant) -> str:  # line 148
    # DDL: UNIQUE(form_id, version)              # line 161
    def _upsert_sql(self, tenant) -> str:        # line 165
    # SQL: ON CONFLICT (form_id, version)        # line 171
    def _load_sql(self, tenant) -> str:          # line 178
    # SQL: WHERE form_id = $1                    # line 182
    def _list_sql(self, tenant) -> str:          # line 199
    # SQL: DISTINCT ON (form_id)                 # line 203
    async def save(self, form, style=None, *, created_by=None, tenant=None) -> str:  # line 279
    async def load(self, form_id, version=None, *, tenant=None) -> FormSchema | None:  # line 325
    async def delete(self, form_id, *, tenant=None) -> bool:  # line 381

# api/handlers.py
class FormAPIHandler:                           # line 46
    def __init__(self, registry, client=None, submission_storage=None,
                 forwarder=None, partial_store=None, ...) -> None:  # line 76
    async def create_form(self, request) -> web.Response:  # line 745
    async def get_form(self, request) -> web.Response:  # line 569
    # Pattern: form_id = request.match_info["form_id"]  # line 571

# api/routes.py
def setup_form_api(app, registry, *, client=None, ..., base_path="/api/v1") -> None:  # line 94
    # Routes use: f"{bp}/forms/{{form_id}}"      # lines 210-213

# api/operations.py
async def handle_operations(request) -> web.Response:  # line 358
    # form_id = request.match_info["form_id"]    # line 374

# tools/create_form.py
def _slugify(text: str) -> str:                  # line 183
class CreateFormInput(BaseModel):                # line 223
    prompt: str                                  # line 233
    form_id: str | None = None                   # line 237
    persist: bool = False                        # line 241
    refine_form_id: str | None = None            # line 245
class CreateFormTool(AbstractTool):              # line 259
    def __init__(self, client, registry=None, model=None, *, tenant=None, **kw):  # line 286
    async def _execute(self, prompt, form_id=None, persist=False,
                       refine_form_id=None, **kw) -> ToolResult:  # line 322
    async def _generate_with_retry(self, messages, form_id) -> FormSchema | None:  # line 505

# services/submissions.py
class FormSubmission(BaseModel):                 # line 50
    submission_id: str = Field(default_factory=...)  # line 86
    form_id: str                                 # line 90
    form_version: str                            # line 91
    # DDL: form_id VARCHAR(255) NOT NULL          # line 181

# services/blob_storage.py
class BlobMetadata(BaseModel):                   # line 55
    form_id: str                                 # line 69
    field_id: str                                # line 70
class _ManagerBackedBlobStorage(AbstractBlobStorage):  # line 180
    def _build_key(self, metadata: BlobMetadata) -> str:  # line 211
        # return f"{self._prefix}{metadata.form_id}/{metadata.field_id}/{blob_id}"  # line 220
```

### Does NOT Exist (Anti-Hallucination)

- ~~`FormSchema.form_uid`~~ — does not exist. Must be added.
- ~~`FormRegistry.get_by_slug()`~~ — does not exist. Must be created.
- ~~`FormRegistry.get_by_uid()`~~ — does not exist. `get()` will be repurposed.
- ~~`FormRegistry._slug_index`~~ — does not exist. Must be created.
- ~~`FormRegistry.list_form_uids()`~~ — does not exist. Must be created.
- ~~`FormSubmission.form_uid`~~ — does not exist. Must be added.
- ~~`BlobMetadata.form_uid`~~ — does not exist. Must be added.
- ~~`extract_form_uid()`~~ — no UUID validation helper exists in handlers or routes.
- ~~`FormAPIHandler.create_blank_form()`~~ — does not exist. Must be created.
- ~~`POST /api/v1/forms/blank`~~ — no such route exists.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Use `Field(default_factory=lambda: str(uuid.uuid4()))` for auto-generation
  (consistent with `FormSubmission.submission_id` pattern at submissions.py:86).
- Follow existing async/lock pattern in `FormRegistry` — all reads/writes under
  `self._lock`.
- Use `web.HTTPBadRequest` for invalid UUID (consistent with existing validation
  patterns in handlers).
- SQL migration should be idempotent (use `IF NOT EXISTS` / `IF EXISTS` guards).

### Known Risks / Gotchas
- **SQL migration on production data**: Run in transaction; test on staging first.
  `form_uid` populated from existing `id` UUID — zero data loss.
- **Submissions backfill may have orphans**: JOIN may miss submissions whose form
  was deleted. Those get `form_uid = NULL`, flagged in migration report.
- **Blob keys for existing uploads**: Existing blobs retain full stored refs in
  form data. Only new uploads use `form_uid`-based keys. No migration needed for
  object storage.
- **Merge conflict with FEAT-388**: FEAT-388 not yet merged. Coordinate by
  updating FormAssembler in the same branch or rebasing after.
- **~1,266 occurrences to update**: Mostly mechanical rename. Grep-verify after
  changes to ensure no `match_info["form_id"]` remains in handlers.

### External Dependencies

No new external dependencies required.

---

## 8. Open Questions

- [ ] Should `form_id` (slug) be globally unique per tenant, or can two forms
  share the same slug? Current design allows slug collisions since `form_uid`
  is the primary key. — *Owner: Jesus*
- [ ] Should the SQL migration be a separate migration script or embedded in
  `_create_table_sql` with idempotent checks? — *Owner: Jesus*

---

## Worktree Strategy

- **Isolation**: per-spec (all tasks run sequentially in one worktree).
- **Parallelism**: Module 1 (FormSchema) must be done first. Modules 3, 7, 8
  can run in parallel after Module 2. Module 4 and 5 can run in parallel after
  Module 2. Module 10 (tests) runs last.
- **Cross-feature dependencies**: FEAT-388 (deterministic CreateFormTool) is in
  a separate worktree and not yet merged. This spec does not depend on it, but
  FEAT-388's FormAssembler will need a follow-up patch to generate `form_uid`
  after this feature merges.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-30 | Jesus Lara | Initial draft |
