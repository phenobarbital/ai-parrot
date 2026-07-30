# Form UID: Stable UUID-Based Form Identity

**Date:** 2026-07-30
**Status:** Draft
**Package:** parrot-formdesigner
**Blast radius:** ~1,266 occurrences across 43+ files

## Problem

`form_id` is a mutable slug derived from the form title (e.g. `untitled-form`,
`customer-feedback`). It serves as the sole identity for forms across URLs,
the in-memory registry, the database, submissions, and blob storage.

This causes:

1. **Non-idempotent URLs** — `PATCH /api/v1/forms/untitled-form/operations`
   breaks if the form is renamed.
2. **No stable reference** — external systems (submissions, blobs, integrations)
   that store `form_id` lose their link when the slug changes.
3. **Wasted DB UUID** — the `form_schemas` table already has
   `id UUID PRIMARY KEY DEFAULT gen_random_uuid()` but it is never exposed to
   the application layer.

## Solution

Introduce `form_uid` (UUID4, auto-generated, immutable) as the primary identity
for all URL routing, registry keys, storage lookups, and cross-system references.
`form_id` remains as a human-readable slug for display and search — never as a
primary key.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Identity field name | `form_uid` | Distinguishes from `form_id` (slug); `uid` signals immutability |
| URL routing | UUID only in path params | Deterministic, idempotent, no ambiguity with slugs |
| Slug lookup | `GET /api/v1/forms?slug=my-form` query param | Clean separation; slug is a search filter, not an address |
| Backwards compatibility | Clean cut, no deprecation | No external clients depend on slug-based URLs |
| Existing DB UUID | Reuse as initial `form_uid` value | Zero data loss on migration |
| Blank form endpoint | `POST /api/v1/forms/blank` | Deterministic form creation without LLM |

---

## 1. Data Model

### FormSchema

```python
class FormSchema(BaseModel):
    form_uid: str = Field(default_factory=lambda: str(uuid.uuid4()))
    form_id: str          # slug, mutable, human-readable
    version: str = "1.0"
    title: LocalizedString
    # ... rest unchanged
```

- `form_uid` is assigned once at creation and never changes.
- `form_id` continues to be generated via `_slugify(title)` or provided by the
  user. It can be renamed freely without breaking references.

### FormField, FormSection, FormSubsection

No changes. These models have no `form_id` back-reference.

---

## 2. FormRegistry (In-Memory Layer)

**File:** `services/registry.py`

### Internal data structures

```python
# Primary index: form_uid → FormSchema
self._forms: dict[str, dict[str, FormSchema]] = {}
#                 tenant   form_uid

# Secondary index: form_id (slug) → form_uid
self._slug_index: dict[str, dict[str, str]] = {}
#                      tenant   form_id  form_uid
```

### Method changes

| Method | Change |
|--------|--------|
| `register(form)` | Store by `form.form_uid`; update `_slug_index[tenant][form.form_id] = form.form_uid` |
| `get(form_uid, tenant=)` | Lookup by `form_uid` in primary index |
| `get_by_slug(form_id, tenant=)` | Lookup `_slug_index` → `form_uid` → primary index |
| `unregister(form_uid, tenant=)` | Remove from both indexes |
| `contains(form_uid, tenant=)` | Check primary index by `form_uid` |
| `list_form_uids(tenant=)` | New method replacing `list_form_ids()` |
| `list_forms(tenant=)` | Unchanged (returns `FormSchema` objects) |
| `clone_form(source_uid, new_form_id)` | Generate new `form_uid` for the clone |

### Tenant isolation

Unchanged. Both indexes are nested under tenant keys.

---

## 3. API Routes and Handlers

### Path parameter rename

All routes change `{form_id}` → `{form_uid}` in the path:

```
GET    /api/v1/forms                          # list (add ?slug= filter)
POST   /api/v1/forms                          # create via LLM (returns form_uid)
POST   /api/v1/forms/blank                    # NEW: create empty form (no LLM)
POST   /api/v1/forms/from-db                  # import from DB (unchanged)
GET    /api/v1/forms/{form_uid}               # get
PUT    /api/v1/forms/{form_uid}               # full replace
PATCH  /api/v1/forms/{form_uid}               # merge-patch
DELETE /api/v1/forms/{form_uid}               # delete
POST   /api/v1/forms/{form_uid}/edit          # LLM edit
POST   /api/v1/forms/{form_uid}/clone         # clone (new form_uid generated)
GET    /api/v1/forms/{form_uid}/schema        # JSON Schema
GET    /api/v1/forms/{form_uid}/style         # style schema
GET    /api/v1/forms/{form_uid}/render/{fmt}  # render
POST   /api/v1/forms/{form_uid}/validate      # validate submission
POST   /api/v1/forms/{form_uid}/data          # submit data
PATCH  /api/v1/forms/{form_uid}/operations    # atomic edits
POST   /api/v1/forms/{form_uid}/fields/{field_id}/upload  # file upload
POST   /api/v1/forms/{form_uid}/partial       # save partial
GET    /api/v1/forms/{form_uid}/partial       # get partial
DELETE /api/v1/forms/{form_uid}/partial       # clear partial
POST   /api/v1/forms/{form_uid}/events/{evt}  # remote event
GET    /api/v1/forms/{form_uid}/audio/ws      # audio WebSocket
POST   /api/v1/forms/{form_uid}/publish       # publish snapshot
GET    /api/v1/forms/{form_uid}/versions      # version history
GET    /api/v1/forms/{form_uid}/versions/{v}  # get frozen version
GET    /api/v1/forms/{form_uid}/import-report # import diff report
```

### UI routes

```
GET  /forms/{form_uid}
POST /forms/{form_uid}
GET  /forms/{form_uid}/schema
GET  /forms/{form_uid}/telegram
POST /api/v1/forms/{form_uid}/telegram-submit
```

### Handler changes

All 18+ handlers change from:

```python
form_id = request.match_info["form_id"]
form = await registry.get(form_id, tenant=tenant)
```

to:

```python
form_uid = request.match_info["form_uid"]
form = await registry.get(form_uid, tenant=tenant)
```

### UUID validation

A helper or middleware validates `form_uid` is a valid UUID before reaching
the handler. Invalid format returns HTTP 400 immediately.

```python
def _extract_form_uid(request: web.Request) -> str:
    raw = request.match_info["form_uid"]
    try:
        uuid.UUID(raw)
    except ValueError:
        raise web.HTTPBadRequest(text=f"Invalid form_uid: {raw!r}, expected UUID")
    return raw
```

### New endpoint: POST /api/v1/forms/blank

Creates an empty form without LLM:

**Request:**
```json
{
  "title": "My Form",
  "form_id": "my-form",
  "tenant": "navigator"
}
```

Only `title` is required. `form_id` is slugified from title if omitted.
`form_uid` is always auto-generated.

**Response:**
```json
{
  "form_uid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "form_id": "my-form",
  "title": "My Form",
  "version": "1.0",
  "sections": [
    {
      "section_id": "section-1",
      "title": "Section 1",
      "fields": []
    }
  ]
}
```

The blank form is registered and persisted immediately. Users build it
incrementally via `PATCH /{form_uid}/operations`.

### Slug search via query param

`GET /api/v1/forms?slug=my-form` uses `registry.get_by_slug()` to find a
form by its slug. Returns the same response as `GET /forms/{form_uid}` if
found, or 404 if not.

---

## 4. CreateFormTool and FormAssembler

### CreateFormTool (`tools/create_form.py`)

- `CreateFormInput` gains `form_uid: str | None = None`.
- `_generate_with_retry()` injects `form_uid` into the LLM result (same
  pattern as `form_id` injection today).
- `_execute()` auto-generates `form_uid` if not provided.
- `refine_form_id` renames to `refine_form_uid` — lookups use UUID.
- `ToolResult.metadata` returns `form_uid` as the primary identifier.

### FormAssembler (FEAT-388)

- `expand_shortcuts()` generates `form_uid = str(uuid.uuid4())` alongside
  `form_id = _slugify(title)`.
- `assemble()` accepts optional `form_uid` parameter as override.

---

## 5. Storage (Database Layer)

### form_schemas table migration

```sql
-- Step 1: Add form_uid column, populate from existing UUID PK
ALTER TABLE {schema}.form_schemas
  ADD COLUMN form_uid VARCHAR(36);

UPDATE {schema}.form_schemas
  SET form_uid = id::text;

ALTER TABLE {schema}.form_schemas
  ALTER COLUMN form_uid SET NOT NULL;

-- Step 2: Replace uniqueness constraint
ALTER TABLE {schema}.form_schemas
  DROP CONSTRAINT form_schemas_form_id_version_key;

ALTER TABLE {schema}.form_schemas
  ADD CONSTRAINT form_schemas_form_uid_version_key UNIQUE(form_uid, version);

-- Step 3: Index for slug search
CREATE INDEX idx_form_schemas_form_id ON {schema}.form_schemas (form_id);
```

### PostgresFormStorage changes

| Operation | Before | After |
|-----------|--------|-------|
| UPSERT conflict | `ON CONFLICT (form_id, version)` | `ON CONFLICT (form_uid, version)` |
| Load | `WHERE form_id = $1` | `WHERE form_uid = $1` |
| List | `DISTINCT ON (form_id)` | `DISTINCT ON (form_uid)` |
| Delete | `WHERE form_id = $1` | `WHERE form_uid = $1` |

### form_data (submissions) table migration

```sql
ALTER TABLE {schema}.form_data
  ADD COLUMN form_uid VARCHAR(36);

UPDATE {schema}.form_data d
  SET form_uid = (
    SELECT s.form_uid FROM {schema}.form_schemas s
    WHERE s.form_id = d.form_id LIMIT 1
  );

CREATE INDEX idx_form_data_form_uid ON {schema}.form_data (form_uid);
```

`form_id` is retained in submissions for human-readable ad-hoc queries.
`form_uid` becomes the stable foreign reference.

### BlobStorage

- New blob keys use `{prefix}{form_uid}/{field_id}/{uuid}`.
- Existing blob keys are not migrated (immutable in object storage).
- Existing blobs remain accessible via their full stored URL/ref — no
  lookup-by-slug needed since blob refs are stored complete in form data.

---

## 6. Testing Strategy

### Existing test updates (~610 occurrences)

Mostly mechanical: replace `form_id` path params with `form_uid` in HTTP
request URLs, update fixture factories to include `form_uid`.

### New test cases

**API tests:**
- `POST /api/v1/forms/blank` — creates empty form, returns `form_uid`
- `GET /api/v1/forms?slug=my-form` — slug search returns correct form
- Invalid UUID in path → 400
- Rename form (change `form_id` slug) → same `form_uid`, URL still works

**Registry tests:**
- `register()` indexes by `form_uid`, updates slug index
- `get(form_uid)` resolves correctly
- `get_by_slug(form_id)` resolves via slug index
- `clone_form()` generates new `form_uid`
- Slug rename does not break `form_uid` lookups

**Storage tests:**
- UPSERT by `(form_uid, version)`
- `load(form_uid)` returns correct form
- Migration integrity: existing forms retain `form_uid` populated from DB `id`

---

## 7. Out of Scope

- **FormField, FormSection, FormSubsection** — no `form_id` references, no changes.
- **Question bank** — no `form_id` column, no changes.
- **FEAT-388 handler update** — the HTTP handler for structured input (passing
  `schema`/`sections`/`fields` to CreateFormTool) is a separate concern.
- **Versioning system** — `form_uid + version` replaces `form_id + version`
  as the composite key, but the versioning semantics are unchanged.

---

## 8. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| SQL migration on production data | High | Run migration in transaction; test on staging first; `form_uid` populated from existing `id` UUID |
| Blob keys for existing uploads | Low | Existing blobs retain full stored refs; only new uploads use `form_uid` keys |
| Submissions backfill incomplete | Medium | JOIN may miss orphaned submissions (form deleted); those get `form_uid = NULL`, flagged in migration report |
| Merge conflict with FEAT-388 | Low | FEAT-388 not yet merged; coordinate by updating FormAssembler in the same branch or rebasing after |
| ~1,266 occurrences to update | Medium | Mostly mechanical rename; grep-verify after changes |
