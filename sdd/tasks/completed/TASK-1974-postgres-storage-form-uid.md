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
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py` | MODIFY | CORRECTED (2026-07-30, added during implementation): `FormRegistry.load_from_storage()` calls `self._storage.load(...)` and reads `item.get("form_id")` from `storage.list_forms()` — since THIS task makes `storage.load()` form_uid-keyed and adds `form_uid` to `list_forms()`'s output dicts, the caller in `registry.py` (Module 2, not nominally in this task's scope) must switch to `item.get("form_uid")` or hydration would silently load zero forms. Flagged as a known TASK-1973/1974 coordination gap in TASK-1973's Completion Note; fixed here. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.schema import FormSchema  # verified: core/__init__.py
from parrot_formdesigner.services.storage import PostgresFormStorage  # verified: services/storage.py:63
```

### Existing Signatures to Use
```python
# CORRECTED (2026-07-30) via full read of services/storage.py — the
# original contract's __init__ signature, return types, and method list
# were stale/incomplete. Actual, verified signatures:

# services/storage.py:63
class PostgresFormStorage(FormStorage):
    # __init__: line 96 — kwarg-only, no positional `pool`/`tenant`
    def __init__(self, *, pool=None, dsn=None, schema=DEFAULT_SCHEMA,
                 table_name=DEFAULT_TABLE, tenant=None,
                 min_size=2, max_size=10, **pool_kwargs) -> None: ...

    # All SQL builders take a `tenant: str | None` param (schema resolution):
    def _create_table_sql(self, tenant: str | None) -> str: ...   # line 148, UNIQUE(form_id, version) at 161
    def _upsert_sql(self, tenant: str | None) -> str: ...         # line 165, ON CONFLICT (form_id, version) at 170
    def _load_sql(self, tenant: str | None) -> str: ...           # line 178, WHERE form_id = $1 at 182
    def _load_version_sql(self, tenant: str | None) -> str: ...  # line 187 — NOT in original contract; also form_id-keyed
    def _delete_sql(self, tenant: str | None) -> str: ...          # line 196 — NOT in original contract; WHERE form_id = $1
    def _list_sql(self, tenant: str | None) -> str: ...           # line 199, DISTINCT ON (form_id) at 202

    # save: line 279 — returns str (form_id), NOT bool as the original
    # contract claimed.
    async def save(self, form: FormSchema, style: StyleSchema | None = None, *,
                    created_by: str | None = None, tenant: str | None = None) -> str: ...

    # load: line 325 — no `version=` default issue, matches original contract.
    async def load(self, form_id: str, version: str | None = None, *,
                    tenant: str | None = None) -> FormSchema | None: ...

    # delete: line 381 — NO `version` parameter (deletes ALL versions of the
    # form) — the original contract's `delete(form_id, version=None)` was
    # WRONG; there is no version param.
    async def delete(self, form_id: str, *, tenant: str | None = None) -> bool: ...

    # list_forms: line 407 — returns dicts with form_id/version/tenant/
    # created_at/title/description (built from schema_json, not from a
    # form_uid column — none exists yet).
    async def list_forms(self, *, tenant: str | None = None) -> list[dict]: ...
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

Implemented as specified: `_create_table_sql` adds `form_uid VARCHAR(36) NOT
NULL`, changes the primary UNIQUE constraint to `(form_uid, version)`, and
adds `UNIQUE(tenant, form_id, version)` for slug uniqueness. `_upsert_sql`
inserts `form_uid` and conflicts on `(form_uid, version)` — additionally
updates `form_id = EXCLUDED.form_id` on conflict (not explicitly listed in
the task, but necessary: without it, renaming a form's slug and re-saving
would silently leave the OLD slug in the storage row, defeating the whole
point of `form_uid`-keyed storage surviving renames). `_load_sql`,
`_load_version_sql`, `_delete_sql`, `_list_sql` all rekeyed to `form_uid`.
`save()`/`load()`/`delete()` renamed their primary parameter accordingly.
Added `load_by_slug(form_id, tenant, version=None)` querying
`WHERE tenant = $1 AND form_id = $2` per the task's own acceptance
criterion (filtering by the `tenant` column value directly, not just via
schema resolution — a deliberate deviation from the sibling `_load_sql`'s
schema-only isolation, done because the task's AC explicitly says
"queries by (tenant, form_id)").

**Codebase Contract corrections**: the original contract's `__init__`
signature, SQL builder signatures (missing the `tenant` parameter on all
of them), `delete()`'s signature (claimed a `version` param that does not
exist), and `save()`'s return type (claimed `bool`, actually `str`) were
all stale/wrong — corrected in this file before implementing. Also found
and documented `_load_version_sql`/`_delete_sql`, two methods the original
contract didn't mention at all.

**Cross-task coordination fix**: `FormRegistry.load_from_storage()` (in
`services/registry.py`, nominally TASK-1973's file) reads
`item.get("form_id")` from `storage.list_forms()` and calls
`self._storage.load(form_id, ...)` — since THIS task makes `list_forms()`
return `form_uid` too and `load()` require it, `load_from_storage()` would
silently hydrate zero forms from a real Postgres backend without this fix.
Updated it to read `item.get("form_uid")` instead. This was explicitly
flagged as a known gap in TASK-1973's own Completion Note; resolved here.
Added `registry.py` to this task's corrected file list.

**New tests**: created `tests/unit/test_storage_form_uid.py` (12 tests)
covering the task's full Test Specification — DDL/constraint content,
`save()`/`load()`/`load_by_slug()`/`delete()` round trips against a
minimal in-memory asyncpg stub, UPSERT conflict target, and the
form-rename-updates-slug behavior. Also updated `tests/unit/test_storage_list.py`
(every `_StubRow` fixture needed a `form_uid` key, since `list_forms()`
now reads `row["form_uid"]` unconditionally) and
`tests/unit/test_storage_schema_tenant.py` (positional arg index for the
`tenant` column in `_upsert_sql`'s param list shifted from 4 to 5 once
`form_uid` became the new first param) and
`tests/unit/test_registry_multi_tenancy.py`
(`test_load_from_storage_per_tenant_no_overwrite`'s mocked
`list_forms()` payload needed a `form_uid` key to match the
`load_from_storage()` fix above).

All storage + registry tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_storage_form_uid.py tests/unit/test_storage_list.py tests/unit/test_storage_pool.py tests/unit/test_storage_schema_tenant.py tests/unit/test_registry_multi_tenancy.py -v` → 98 passed.

Ruff: net zero new lint issues across all touched files except one BLE001
(`except Exception` in the new `load_by_slug()`) that mirrors the exact
same pre-existing pattern used in every other method in this file — left
as-is for consistency, not fixed.

Full `pytest tests/unit/` failure set is byte-for-byte identical to the
post-TASK-1973 baseline (confirmed via diff) — this task introduces zero
new regressions.
