---
type: feature
base_branch: dev
---

# Feature Specification: Enriched List of Created Forms in parrot-formdesigner

**Feature ID**: FEAT-148
**Date**: 2026-05-05
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.10.x

---

## 1. Motivation & Business Requirements

### Problem Statement

The `parrot-formdesigner` package exposes `GET /api/v1/forms`, but the current
implementation in `FormAPIHandler.list_forms()` only returns a flat list of
`form_id` strings:

```json
{ "forms": ["form-a", "form-b", "form-c"] }
```

This is not enough to drive a meaningful UI. Front-ends that need to render a
"created forms" list (gallery, dashboard, picker) cannot show titles,
descriptions, version, or creation dates without making N additional
`GET /api/v1/forms/{form_id}` round-trips. There is also no merge between
in-memory forms (those registered via YAML, `CreateFormTool`, or
`DatabaseFormTool`) and persisted forms in `PostgresFormStorage` that have not
yet been hydrated into the registry — consumers see only what is in memory.

`FormSchema` itself has no `created_at` field, although `PostgresFormStorage`
records it in the `form_schemas` table (column `created_at TIMESTAMPTZ`).
That timestamp is currently invisible to API consumers.

### Goals

- Replace the response of `GET /api/v1/forms` with a list of rich form
  descriptors (`form_id`, `title`, `description`, `version`, `source`,
  `created_at`).
- Merge registry-backed forms and storage-backed forms in a single response
  so persisted forms not yet loaded into memory are still listed.
- Extend `FormSchema` with an optional `created_at: datetime | None` field
  (default `None`) so the timestamp can flow end-to-end.
- Update `PostgresFormStorage.list_forms()` to surface `created_at` and
  `description` alongside `form_id`, `version`, `title`.
- Keep the endpoint path (`GET /api/v1/forms`) and its auth wrapping
  unchanged — only the response payload shape changes.

### Non-Goals (explicitly out of scope)

- Pagination (`limit`/`offset`) — full listing is acceptable for current volumes.
- Filtering by `org_id`, `programs`, or any role-based scoping — out of scope;
  the endpoint returns every form visible to the authenticated user.
- Search/query parameters (e.g. `?q=`).
- Adding `updated_at` to `FormSchema` — only `created_at` is required for
  the date-sort goal.
- Modifying `FormStorage.save()` signature.
- Per-form permission checks against `FormPermissionChecker` (FEAT-077).
- Bumping `FormSchema.version` semantics — the new optional field is
  additive and backwards-compatible at the schema level.

---

## 2. Architectural Design

### Overview

This feature is a small, focused refactor of one HTTP handler plus two
supporting changes:

1. `FormSchema` gains an optional `created_at: datetime | None = None` field.
2. `PostgresFormStorage.list_forms()` returns richer entries, including
   `created_at` (ISO-8601) and `description`, and the `LIST_SQL` query is
   updated to project those columns.
3. `FormAPIHandler.list_forms()` merges:
   - `await self.registry.list_forms()` → in-memory `FormSchema` objects
   - `await self.registry._storage.list_forms()` (when configured) →
     persisted entries not present in the registry
   …into a single deduplicated list of descriptor dicts.

The merge is keyed by `form_id`. When a form is in both sources, the
registry's in-memory `FormSchema` wins for `title`/`description`/`version`,
and `created_at` is taken from the storage row (registry lacks creation
timestamps unless the form was loaded from storage).

The `source` field is computed:
- `"memory"` → form is in the registry and **not** in storage.
- `"db"` → form is in storage (regardless of whether it is also in the registry).

### Component Diagram

```
                         ┌────────────────────────┐
                         │ GET /api/v1/forms      │
                         │ (FormAPIHandler.list_  │
                         │  forms)                │
                         └──────────┬─────────────┘
                                    │
                ┌───────────────────┴────────────────────┐
                ▼                                        ▼
       ┌─────────────────┐                    ┌──────────────────────┐
       │  FormRegistry   │                    │ FormStorage          │
       │  .list_forms()  │                    │ .list_forms() (opt.) │
       │  → [FormSchema] │                    │ → [dict descriptors] │
       └─────────────────┘                    └──────────────────────┘
                │                                        │
                └────────────── merge by form_id ────────┘
                                    │
                                    ▼
                       [{form_id, title, description,
                         version, source, created_at}]
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FormSchema` | extends | Add optional `created_at: datetime \| None = None` field |
| `FormRegistry.list_forms()` | uses | Source of in-memory `FormSchema` objects |
| `FormRegistry._storage` | reads | Optional `FormStorage` reference; merged when present |
| `FormStorage.list_forms()` | extends | Docstring update — implementations should include `created_at` and `description` when available |
| `PostgresFormStorage.list_forms()` | modifies | Add `created_at`, `description` to projected columns and returned dicts |
| `FormAPIHandler.list_forms()` | modifies | New merge logic + new response shape |
| `setup_form_routes()` | unchanged | Same path, same auth wrapping |

### Data Models

```python
# Response item (no Pydantic model needed; built as a dict in the handler)
{
    "form_id": str,
    "title": str,                     # LocalizedString flattened to str
    "description": str | None,        # LocalizedString flattened to str | None
    "version": str,
    "source": Literal["memory", "db"],
    "created_at": str | None,         # ISO-8601 (UTC) or None
}
```

```python
# Schema change
class FormSchema(BaseModel):
    form_id: str
    version: str = "1.0"
    title: LocalizedString
    description: LocalizedString | None = None
    sections: list[FormSection]
    submit: SubmitAction | None = None
    cancel_allowed: bool = True
    meta: dict[str, Any] | None = None
    created_at: datetime | None = None   # NEW — ISO-serialized in JSON
```

### New Public Interfaces

No new public classes are introduced. The public-facing changes are:

1. `FormSchema.created_at` — new optional attribute.
2. `GET /api/v1/forms` response — new shape (see below).

**New response shape:**

```json
{
  "forms": [
    {
      "form_id": "assembly-checklist",
      "title": "Assembly Checklist",
      "description": "Daily assembly report",
      "version": "1.2",
      "source": "db",
      "created_at": "2026-04-12T10:31:00+00:00"
    },
    {
      "form_id": "ad-hoc-form",
      "title": "Ad hoc",
      "description": null,
      "version": "1.0",
      "source": "memory",
      "created_at": null
    }
  ]
}
```

Order: ascending by `form_id` for determinism. (Date-based ordering is
deferred to the client; `created_at` is provided so the UI can sort.)

---

## 3. Module Breakdown

### Module 1: FormSchema — `created_at` field

- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py`
- **Responsibility**:
  - Add `from datetime import datetime` import.
  - Add `created_at: datetime | None = None` to `FormSchema`.
  - Update the class docstring `Attributes:` block.
- **Depends on**: nothing.

### Module 2: PostgresFormStorage — enriched `list_forms()`

- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py`
- **Responsibility**:
  - Update `LIST_SQL` to project `created_at` and the `schema_json->>'description'`
    (or extract via JSON parsing, consistent with the existing `title`
    extraction).
  - Update `list_forms()` to include `created_at` (as ISO-8601 string) and
    `description` in each result dict.
  - Keep the return type `list[dict[str, str]]` annotation but document that
    `created_at` may be a string or omitted.
- **Depends on**: nothing (Module 1 not strictly required because storage
  reads `schema_json` directly, but Module 1 lets in-memory forms loaded
  from this storage carry `created_at` forward).

### Module 3: FormStorage ABC — docstring contract update

- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py`
  (within the `FormStorage` ABC block, lines ~29–91)
- **Responsibility**:
  - Update `FormStorage.list_forms()` docstring to state that returned dicts
    SHOULD include `form_id`, `version`, `title`, and MAY include
    `description` and `created_at` when available.
  - No signature change.
- **Depends on**: nothing.

### Module 4: FormAPIHandler.list_forms — merged rich listing

- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py`
- **Responsibility**:
  - Replace the body of `list_forms()`.
  - Fetch `await self.registry.list_forms()` → `list[FormSchema]`.
  - If `self.registry._storage is not None`, also fetch
    `await self.registry._storage.list_forms()` → `list[dict]`.
  - Merge by `form_id` (registry wins for `title`/`description`/`version`;
    `created_at` falls back to storage row → registry's
    `FormSchema.created_at` → `None`).
  - Flatten `LocalizedString` (which is `str | dict[str, str]`) to a plain
    string by picking the first dict value when a dict, otherwise using the
    string directly. Reuse the same flattening logic already used in
    `PostgresFormStorage.list_forms()` (extract into a small private
    helper in the handler module: `_loc_to_str(value) -> str | None`).
  - Sort final list ascending by `form_id`.
  - Return `web.json_response({"forms": [<descriptor>, ...]})`.
- **Depends on**: Modules 1, 2, 3.

### Module 5: Tests — handlers + storage + schema

- **Path**:
  - `packages/parrot-formdesigner/tests/unit/test_handlers.py`
  - `packages/parrot-formdesigner/tests/unit/test_core_models.py` (or a new
    `test_form_schema_created_at.py`)
- **Responsibility**:
  - Update existing tests `test_list_forms_empty` and
    `test_list_forms_with_registered_form` to assert the new dict-shaped
    payload (`data["forms"]` is a list of dicts; each item has `form_id`,
    `title`, `version`, `source`, and `created_at` keys).
  - Add new tests:
    - `test_list_forms_dict_shape` — registry-only form yields one
      descriptor with `source == "memory"` and `created_at is None`.
    - `test_list_forms_with_storage_only_form` — fake storage returns a
      form not in the registry; descriptor has `source == "db"` and
      ISO-8601 `created_at`.
    - `test_list_forms_storage_and_registry_dedupe` — same `form_id` in
      both; one descriptor; registry's title/version wins; `created_at`
      from storage.
    - `test_list_forms_localized_title_flattening` — `title` as
      `{"en": "Hello", "es": "Hola"}` flattens to a string (first value).
    - `test_list_forms_sorted_by_form_id` — multiple forms come back in
      `form_id` ASC order.
  - Add `test_form_schema_created_at_optional` — `FormSchema(...)` without
    `created_at` parses; with a `datetime`, it round-trips through
    `model_dump()` / `model_validate()` and serializes as ISO-8601 in
    `model_dump_json()`.
- **Depends on**: Modules 1–4.

### Module 6: PostgresFormStorage tests

- **Path**: There is no existing `test_storage.py` — tests for
  `PostgresFormStorage.list_forms()` are integration-only.
- **Responsibility**: Add a unit test using a stub `pool.acquire()` /
  fake `conn.fetch()` returning a synthetic row with `created_at` and a
  `schema_json` containing a description, and assert the dict shape.
  - **Path**: `packages/parrot-formdesigner/tests/unit/test_storage_list.py` (new).
- **Depends on**: Module 2.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_form_schema_created_at_optional` | 1 | `FormSchema` parses without `created_at`; round-trips with one |
| `test_form_schema_created_at_serializes_iso` | 1 | `model_dump_json()` renders `created_at` as ISO-8601 |
| `test_postgres_list_forms_includes_created_at` | 2,6 | Stubbed `pool` returns a row with `created_at`; result dict has ISO string |
| `test_postgres_list_forms_includes_description` | 2,6 | Description from `schema_json` is surfaced |
| `test_form_storage_docstring` | 3 | `FormStorage.list_forms.__doc__` mentions `created_at` and `description` (lightweight contract test) |
| `test_list_forms_empty` (UPDATED) | 4,5 | Empty registry/no storage → `{"forms": []}` |
| `test_list_forms_dict_shape` | 4,5 | One registry form → one descriptor with required keys |
| `test_list_forms_localized_title_flattening` | 4,5 | Dict-typed `title` flattens to first string value |
| `test_list_forms_with_storage_only_form` | 4,5 | Form in storage but not in registry appears with `source="db"` |
| `test_list_forms_storage_and_registry_dedupe` | 4,5 | Form in both: one descriptor; registry wins for title/version; storage wins for `created_at` |
| `test_list_forms_sorted_by_form_id` | 4,5 | Descriptors sorted ASC by `form_id` |
| `test_list_forms_storage_failure_falls_back_to_registry` | 4,5 | Storage raises → handler logs warning and returns registry-only list (no 500) |

### Integration Tests

| Test | Description |
|---|---|
| `test_list_forms_end_to_end` | Register two forms via `FormRegistry`, attach a `PostgresFormStorage`-stub with one extra form, call `GET /api/v1/forms`, assert merged response with three items |

### Test Data / Fixtures

```python
@pytest.fixture
def storage_only_descriptor():
    """A form descriptor returned by FormStorage.list_forms() that is NOT in the registry."""
    return {
        "form_id": "persisted-only",
        "version": "1.0",
        "title": "Persisted Only",
        "description": "Lives only in storage",
        "created_at": "2026-04-12T10:31:00+00:00",
    }

class FakeStorage(FormStorage):
    """In-memory test double for FormStorage."""
    def __init__(self, rows): self._rows = rows
    async def save(self, form, style=None): return form.form_id
    async def load(self, form_id, version=None): return None
    async def delete(self, form_id): return False
    async def list_forms(self): return list(self._rows)
```

---

## 5. Acceptance Criteria

- [ ] `FormSchema.created_at: datetime | None = None` exists and is optional.
- [ ] `FormSchema(...)` calls without `created_at` continue to work
      (no breaking change at schema construction time).
- [ ] `model_dump_json()` of a `FormSchema` with `created_at` set emits an
      ISO-8601 string.
- [ ] `PostgresFormStorage.list_forms()` returns dicts that include
      `form_id`, `version`, `title`, `description`, and `created_at`
      (ISO-8601 string) for every row.
- [ ] `GET /api/v1/forms` returns `{"forms": [<dict>, ...]}` where each
      dict has the keys `form_id`, `title`, `description`, `version`,
      `source`, `created_at`.
- [ ] Forms only in `FormRegistry` (in-memory) appear with
      `source == "memory"` and `created_at is None` (unless the
      `FormSchema.created_at` was explicitly populated by an extractor).
- [ ] Forms in `FormStorage` but not in the registry appear with
      `source == "db"` and ISO-8601 `created_at`.
- [ ] When a form is in both sources, exactly one descriptor is returned,
      registry wins for `title`/`description`/`version`, and `created_at`
      is taken from the storage row.
- [ ] `LocalizedString` titles/descriptions are flattened to plain strings
      in the response.
- [ ] Result list is sorted ascending by `form_id`.
- [ ] When `FormStorage.list_forms()` raises, the handler logs a warning
      via `self.logger` and still returns the registry-only list (no 500).
- [ ] Endpoint remains protected by `_wrap_auth` exactly as today.
- [ ] All updated and new unit tests pass: `pytest packages/parrot-formdesigner/tests/unit/ -v`.
- [ ] No changes to any route registration or `setup_form_routes()` signature.
- [ ] `CHANGELOG`/release notes call out the breaking response change to
      `GET /api/v1/forms` (consumers expecting `list[str]` must migrate).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Every reference below was
> verified by reading the file on branch `dev` at the time this spec was
> written. Implementing agents MUST use these exact symbols and paths.

### Verified Imports

```python
# Schema and types
from parrot.formdesigner.core.schema import FormSchema, FormSection, FormField
# verified: packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py:107
from parrot.formdesigner.core.types import FieldType, LocalizedString
# verified: packages/parrot-formdesigner/src/parrot/formdesigner/core/types.py:13

# Services
from parrot.formdesigner.services.registry import FormRegistry, FormStorage
# verified: packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py:94, :29
from parrot.formdesigner.services.storage import PostgresFormStorage
# verified: packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py:39
from parrot.formdesigner.services import (
    FormCache, FormRegistry, FormStorage, PostgresFormStorage,
)
# verified: packages/parrot-formdesigner/src/parrot/formdesigner/services/__init__.py

# Handlers
from parrot.formdesigner.handlers import FormAPIHandler, setup_form_routes
# verified: packages/parrot-formdesigner/src/parrot/formdesigner/handlers/__init__.py
```

### Existing Class Signatures

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/core/types.py
LocalizedString = str | dict[str, str]                   # line 13

# packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py
class FormSchema(BaseModel):                              # line 107
    form_id: str                                          # line 125
    version: str = "1.0"                                  # line 126
    title: LocalizedString                                # line 127
    description: LocalizedString | None = None            # line 128
    sections: list[FormSection]                           # line 129
    submit: SubmitAction | None = None                    # line 130
    cancel_allowed: bool = True                           # line 131
    meta: dict[str, Any] | None = None                    # line 132
    # NOTE: FormSchema does NOT set extra="forbid" — adding the new
    # `created_at` field is backwards-compatible at parse time.

# packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py
class FormStorage(ABC):                                   # line 29
    async def save(self, form, style=None) -> str: ...    # line 39
    async def load(self, form_id, version=None) -> FormSchema | None: ...  # line 56
    async def delete(self, form_id) -> bool: ...          # line 73
    async def list_forms(self) -> list[dict[str, str]]: ...  # line 85

class FormRegistry:                                       # line 94
    def __init__(self, storage: FormStorage | None = None) -> None: ...  # line 111
    self._forms: dict[str, FormSchema]                    # line 117
    self._storage = storage                               # line 119
    async def register(self, form, *, persist=False, overwrite=True) -> None: ...  # line 124
    async def get(self, form_id) -> FormSchema | None: ...  # line 192
    async def list_forms(self) -> list[FormSchema]: ...   # line 204  ← used by Module 4
    async def list_form_ids(self) -> list[str]: ...       # line 213  ← currently used by handler
    async def load_from_storage(self) -> int: ...         # line 290

# packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py
class PostgresFormStorage(FormStorage):                   # line 39
    LIST_SQL = """
    SELECT DISTINCT ON (form_id) form_id, version, schema_json, updated_at
    FROM form_schemas
    ORDER BY form_id, updated_at DESC
    """                                                   # line 100
    async def list_forms(self) -> list[dict[str, str]]:   # line 213
        # Currently returns: {"form_id", "version", "title"}
        # Module 2 will extend with: + "description", + "created_at"

# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py
class FormAPIHandler:                                     # line 85
    def __init__(self, registry, client=None,
                 submission_storage=None, forwarder=None) -> None: ...  # line 101
    self.registry: FormRegistry                           # line 108
    self.logger = logging.getLogger(__name__)             # line 115
    async def list_forms(self, request) -> web.Response:  # line 200  ← REPLACE BODY
        # Current body (line 209): form_ids = await self.registry.list_form_ids()
        # Current body (line 210): return web.json_response({"forms": form_ids})

# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py
app.router.add_get(f"{p}/api/v1/forms", _wrap_auth(api.list_forms))
# verified: packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py:148
```

### DB Schema Reference

```sql
-- packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py:58-70
CREATE TABLE IF NOT EXISTS form_schemas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    form_id VARCHAR(255) NOT NULL,
    version VARCHAR(50) NOT NULL DEFAULT '1.0',
    schema_json JSONB NOT NULL,
    style_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),       -- ← surfaced now
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by VARCHAR(255),
    UNIQUE(form_id, version)
);
```

### Existing Tests That Will Need Updating

```python
# packages/parrot-formdesigner/tests/unit/test_handlers.py
async def test_list_forms_empty(...)           # line 55  — assert new shape
async def test_list_forms_with_registered_form(...)  # line 78  — currently does:
    #   assert "test" in data["forms"]   ← MUST become: any(f["form_id"] == "test" for f in data["forms"])
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| Refactored `FormAPIHandler.list_forms` | `FormRegistry.list_forms()` | method call | `services/registry.py:204` |
| Refactored `FormAPIHandler.list_forms` | `FormRegistry._storage.list_forms()` | conditional method call (when `_storage is not None`) | `services/registry.py:119` |
| `FormSchema.created_at` | `PostgresFormStorage.load()` | hydrated when reading `schema_json` | `services/storage.py:158-192` |
| `PostgresFormStorage.list_forms()` (updated) | `LIST_SQL` (updated) | SQL projection | `services/storage.py:100,213` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.formbuilder`~~ — the package is `parrot.formdesigner` (note the spelling).
- ~~`FormRegistry.created_at`~~ — registry does not track creation timestamps;
  use `FormSchema.created_at` (Module 1) or `PostgresFormStorage` rows.
- ~~`FormRegistry.list_forms_with_metadata()`~~ — no such helper; the merge
  belongs in the handler.
- ~~`FormRegistry.storage` (public)~~ — the attribute is `_storage` (private);
  the handler accesses it directly. (Adding a public accessor is not in scope.)
- ~~`FormStorage.list_descriptors()`~~ — does not exist; use `list_forms()`.
- ~~`FormSchema.updated_at`~~ — explicitly out of scope; do not add it.
- ~~`FormPermissionChecker`~~ scoping inside `list_forms()` — not in scope
  (FEAT-077 territory).
- ~~A new endpoint `GET /api/v1/forms/list` or `?detail=full`~~ — explicitly
  rejected; we enrich the existing endpoint.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Use `self.logger` for all warnings (storage failure, malformed rows).
- Keep the `LocalizedString` flattening rule consistent with the existing
  one in `PostgresFormStorage.list_forms()` (`storage.py:236-238`):
  ```python
  if isinstance(value, dict):
      value = next(iter(value.values()), "")
  return str(value) if value else None
  ```
  Extract this into a small module-level helper in `handlers/api.py`
  (`_loc_to_str`) — do NOT scatter the snippet across the handler.
- Pydantic v2 serialization: `datetime | None` round-trips as ISO-8601
  automatically via `model_dump_json()`. No custom serializer needed.
- Sort key: `lambda d: d["form_id"]` — deterministic and cheap.

### SQL Update for Module 2

```sql
SELECT DISTINCT ON (form_id)
    form_id,
    version,
    schema_json,
    created_at,                     -- NEW projection
    updated_at
FROM form_schemas
ORDER BY form_id, updated_at DESC
```

In Python (`PostgresFormStorage.list_forms`), build the dict as:

```python
created_at = row["created_at"]
entry: dict[str, Any] = {
    "form_id": row["form_id"],
    "version": row["version"],
    "created_at": created_at.isoformat() if created_at is not None else None,
}
# Extract title and description from schema_json (consistent with current code)
```

### Known Risks / Gotchas

- **Breaking response change**: this is a deliberate, documented break of
  `GET /api/v1/forms`. The package is at `0.10.x` target; mention the
  migration in the changelog. Existing consumers iterating over
  `data["forms"]` as a list of strings must switch to reading
  `item["form_id"]`. Two existing tests
  (`test_list_forms_empty`, `test_list_forms_with_registered_form`)
  must be updated in the same task as the handler.
- **`FormRegistry._storage` is private**: the handler reaches into a
  protected attribute. This mirrors what `update_form()` and
  `patch_form()` already do at `api.py:391` and `api.py:442` — do not
  introduce a public accessor in this spec.
- **Storage failure must not break the endpoint**: wrap the
  `await self.registry._storage.list_forms()` call in `try/except`,
  log via `self.logger.warning(...)`, and continue with registry-only
  data. (Acceptance criterion + dedicated test.)
- **Empty / missing fields in storage rows**: `description` may be
  absent, `null`, or a localized dict — handle all three the same way
  as `title` is handled today.
- **`created_at` in registry**: in-memory forms registered via
  `FormRegistry.register()` have `FormSchema.created_at = None` unless
  the producer set it (e.g. `PostgresFormStorage.load()` could populate
  it once `schema_json` round-trips through Pydantic). Out of scope to
  guarantee population for memory-only forms.
- **Time zone**: `TIMESTAMPTZ` returns a tz-aware `datetime` from
  asyncpg. `.isoformat()` will include the offset (e.g. `+00:00`).
  Tests should not assume UTC-only output, just well-formed ISO-8601.
- **Sort stability with localized titles**: sorting by `form_id` (not
  by `title`) sidesteps locale-dependent collation.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2.0` (already pinned in `pyproject.toml`) | `datetime` field on `FormSchema` |
| `asyncpg` | (already used by `PostgresFormStorage`) | No new requirement |

No new dependencies are added.

---

## 8. Open Questions

> All required design questions were answered in the planning conversation
> on 2026-05-05; recorded here for the audit trail.

- [x] Package name — *Resolved*: `parrot-formdesigner` (in
      `packages/parrot-formdesigner/`). The user request mentioned
      "parrot-formbuilder"; this is a colloquial alias for the same package.
- [x] Endpoint placement — *Resolved*: enrich the existing
      `GET /api/v1/forms`; do not add a new endpoint.
- [x] Returned fields — *Resolved*: `form_id`, `title`, `description`,
      `version`, `source`, `created_at`. Adding `created_at` requires
      extending `FormSchema`.
- [x] Source of data — *Resolved*: merge `FormRegistry` (in-memory) with
      `FormStorage.list_forms()` (persisted). Registry wins for
      title/description/version; storage wins for `created_at`.
- [x] Authorization scoping — *Resolved*: no `org_id`/`programs`
      filtering; return all forms visible to the authenticated role.
- [x] Pagination — *Resolved*: out of scope; full listing.

No `[ ]` open items remain.

---

## Worktree Strategy

- **Isolation**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: Five small touch points across one package
  (`packages/parrot-formdesigner/`); no parallelizable work; single
  reviewer surface; tests for Module 2/4 share fixtures.
- **Cross-feature dependencies**: None.
  - FEAT-078 (`formbuilder-database`) is merged; this spec does not
    touch `DatabaseFormTool`.
  - FEAT-077 (PBAC / `FormPermissionChecker`) is explicitly out of
    scope here; if it lands, a follow-up can add scoping inside the
    same handler.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-05 | Jesus Lara | Initial draft (no prior brainstorm) |
