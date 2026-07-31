# TASK-1974: PostgresFormStorage DDL and query updates

**Feature**: FEAT-389 — Stable UUID-Based Form Identity
**Spec**: `sdd/specs/form-uid-stable-identity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-1972
**Assigned-to**: unassigned

---

## Context

The PostgresFormStorage service owns the SQL DDL and all query methods for
persisting `FormSchema` objects. Currently keyed on `(form_id, version)`, it
must be rekeyed on `(form_uid, version)` so that renaming a form's slug never
breaks stored references. A new `load_by_slug()` method preserves backward-
compatible slug-based lookups. Implements Module 3 from the spec.

---

## Scope

- Update `_create_table_sql` (greenfield DDL):
  - Add `form_uid VARCHAR(36) NOT NULL` column.
  - Change UNIQUE constraint from `(form_id, version)` to `(form_uid, version)`.
  - Add secondary UNIQUE constraint `(tenant, form_id, version)` for slug uniqueness.
- Update `_upsert_sql`: change `ON CONFLICT (form_id, version)` to
  `ON CONFLICT (form_uid, version)`. Include `form_uid` in INSERT column list.
- Update `_load_sql`: change `WHERE form_id = $1` to `WHERE form_uid = $1`.
- Update `_list_sql`: change `DISTINCT ON (form_id)` to `DISTINCT ON (form_uid)`.
- Update `save()` method to pass `form_uid` to the query parameters.
- Update `load()` method to accept and query by `form_uid`.
- Update `delete()` method to accept and delete by `form_uid`.
- Add `load_by_slug(form_id: str, tenant: str, version: str | None = None) -> FormSchema | None`
  method that queries by `(tenant, form_id)` and returns the latest version.

**NOT in scope**: Migration scripts (TASK-1975), API route changes (TASK-1976),
submissions DDL (TASK-1979).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py` | MODIFY | DDL, queries, save/load/delete, add `load_by_slug()` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.schema import FormSchema  # verified: core/__init__.py
from parrot_formdesigner.services.storage import PostgresFormStorage  # verified: services/storage.py:63
```

### Existing Signatures to Use
```python
# services/storage.py:63
class PostgresFormStorage:
    # __init__: line 96
    def __init__(self, pool, tenant: str = "default", ...): ...

    # _create_table_sql: line 148
    # DDL with UNIQUE(form_id, version) at line 161
    def _create_table_sql(self) -> str: ...

    # _upsert_sql: line 165
    # ON CONFLICT (form_id, version) at line 171
    def _upsert_sql(self) -> str: ...

    # _load_sql: line 178
    # WHERE form_id=$1 at line 182
    def _load_sql(self) -> str: ...

    # _list_sql: line 199
    # DISTINCT ON (form_id) at line 203
    def _list_sql(self) -> str: ...

    # save: line 279
    async def save(self, schema: FormSchema, ...) -> bool: ...

    # load: line 325
    async def load(self, form_id: str, version: str | None = None) -> FormSchema | None: ...

    # delete: line 381
    async def delete(self, form_id: str, version: str | None = None) -> bool: ...
```

### Does NOT Exist
- ~~`PostgresFormStorage.load_by_slug()`~~ — does not exist yet. This task creates it.
- ~~`form_uid` column in DDL~~ — does not exist yet. This task adds it.
- ~~`UNIQUE(form_uid, version)` constraint~~ — does not exist yet.

---

## Implementation Notes

### DDL Changes (greenfield)
```sql
CREATE TABLE IF NOT EXISTS form_schemas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    form_uid VARCHAR(36) NOT NULL,     -- NEW: immutable UUID identity
    form_id VARCHAR(255) NOT NULL,     -- mutable slug, kept for human readability
    tenant VARCHAR(255) NOT NULL DEFAULT 'default',
    version VARCHAR(50) NOT NULL DEFAULT '1.0',
    -- ... other columns unchanged ...
    UNIQUE(form_uid, version),              -- PRIMARY uniqueness
    UNIQUE(tenant, form_id, version)        -- slug uniqueness per tenant
);
```

### Query parameter ordering
When updating `_upsert_sql`, ensure `form_uid` is included in both the column
list and VALUES placeholder list. The parameter position in `save()` must match.

### `load_by_slug()` pattern
```python
async def load_by_slug(
    self, form_id: str, tenant: str, version: str | None = None
) -> FormSchema | None:
    """Load a form by its slug (form_id) + tenant, returning latest version."""
    # Query: WHERE tenant = $1 AND form_id = $2 ORDER BY version DESC LIMIT 1
```

### Key Constraints
- All existing tests that call `load(form_id=...)` must continue to work via
  `load_by_slug()` or by updating to pass `form_uid`.
- The `form_uid` column must be `NOT NULL` — every row must have one.

---

## Acceptance Criteria

- [ ] `_create_table_sql` includes `form_uid VARCHAR(36) NOT NULL` column
- [ ] Primary UNIQUE constraint is `(form_uid, version)`
- [ ] Secondary UNIQUE constraint is `(tenant, form_id, version)`
- [ ] `_upsert_sql` uses `ON CONFLICT (form_uid, version)`
- [ ] `_load_sql` uses `WHERE form_uid = $1`
- [ ] `_list_sql` uses `DISTINCT ON (form_uid)`
- [ ] `save()` passes `form_uid` from `FormSchema` to query
- [ ] `load()` accepts and queries by `form_uid`
- [ ] `delete()` accepts and deletes by `form_uid`
- [ ] `load_by_slug()` method exists and queries by `(tenant, form_id)`
- [ ] All changes are backward-compatible with existing callers (via `load_by_slug`)

---

## Test Specification
```python
import pytest

@pytest.mark.asyncio
async def test_save_and_load_by_form_uid(storage):
    """Save a form, then load it by form_uid."""
    schema = make_test_schema(form_uid="test-uid-001", form_id="my-form")
    await storage.save(schema)
    loaded = await storage.load(form_uid="test-uid-001")
    assert loaded is not None
    assert loaded.form_uid == "test-uid-001"

@pytest.mark.asyncio
async def test_load_by_slug(storage):
    """Load a form by its mutable slug."""
    schema = make_test_schema(form_uid="test-uid-002", form_id="slug-form")
    await storage.save(schema)
    loaded = await storage.load_by_slug(form_id="slug-form", tenant="default")
    assert loaded is not None
    assert loaded.form_uid == "test-uid-002"

@pytest.mark.asyncio
async def test_upsert_conflict_on_form_uid_version(storage):
    """Upsert uses (form_uid, version) as conflict target."""
    schema = make_test_schema(form_uid="test-uid-003", form_id="upsert-form")
    await storage.save(schema)
    schema.title = "Updated Title"
    await storage.save(schema)  # should update, not duplicate
    loaded = await storage.load(form_uid="test-uid-003")
    assert loaded.title == "Updated Title"

@pytest.mark.asyncio
async def test_list_distinct_on_form_uid(storage):
    """List returns one entry per form_uid."""
    pass  # verify DISTINCT ON (form_uid) grouping

@pytest.mark.asyncio
async def test_delete_by_form_uid(storage):
    """Delete by form_uid removes the form."""
    pass
```

---

## Agent Instructions

1. Read this task file and the spec (Module 3).
2. Read `services/storage.py` in full to understand current DDL and queries.
3. Verify TASK-1972 is complete (`FormSchema.form_uid` exists).
4. Implement all scope items.
5. Run existing tests: `pytest packages/parrot-formdesigner/tests/ -v -k storage`
6. Add new tests per test specification.
7. Commit with message: `sdd: TASK-1974 — PostgresFormStorage DDL and query updates for form_uid`
8. Update this task status to `done`.

---

## Completion Note
*(Agent fills this in when done)*
