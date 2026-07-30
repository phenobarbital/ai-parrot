# TASK-1982: Tests — update existing and add new for form_uid

**Feature**: FEAT-389 — Stable UUID-Based Form Identity
**Spec**: `sdd/specs/form-uid-stable-identity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL
**Depends-on**: TASK-1972, TASK-1973, TASK-1974, TASK-1975, TASK-1976, TASK-1977, TASK-1978, TASK-1979, TASK-1980, TASK-1981
**Assigned-to**: unassigned

---

## Context

This is the final integration and validation task. All prior tasks (TASK-1972
through TASK-1981) add `form_uid` across the stack. This task ensures comprehensive
test coverage: updating existing tests to use `form_uid` and adding new tests for
all new functionality. Implements Module 10 from the spec.

---

## Scope

### Update existing tests
- Update ALL test helpers and fixtures in `packages/parrot-formdesigner/tests/`
  to include `form_uid` when constructing `FormSchema`, `FormSubmission`,
  `BlobMetadata`, and related objects.
- Update ALL API test URLs from `/{form_id}` to `/{form_uid}` paths.
- Update registry test assertions to use `form_uid` as the primary key.

### Add new tests
- **Blank form creation**: `POST /forms/blank` returns 200/201 with `form_uid`.
- **Slug search**: `GET /forms?slug=my-form` returns filtered results.
- **UUID validation**: `GET /forms/not-a-uuid` returns 400 JSON error.
- **Form rename stability**: Renaming `form_id` (slug) does not change `form_uid`;
  the form remains accessible by UUID.
- **Registry dual-index**: Verify `_slug_index` with `tenant_form_slug` key
  correctly maps to `form_uid` in the primary index.
- **Slug uniqueness per tenant**: Two forms in the same tenant cannot have the
  same `form_id` (slug) mapped to different `form_uid` values.
- **Storage migration integrity**: After running migration SQL, all rows have
  valid `form_uid` values.
- **Migration idempotency**: Running migration scripts twice produces no errors
  and no duplicate data.

**NOT in scope**: Implementation changes — this task only adds/updates tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/conftest.py` | MODIFY | Update shared fixtures to include `form_uid` |
| `packages/parrot-formdesigner/tests/test_schema.py` | MODIFY | Update FormSchema tests for `form_uid` |
| `packages/parrot-formdesigner/tests/test_registry.py` | MODIFY | Update registry tests, add dual-index and slug tests |
| `packages/parrot-formdesigner/tests/test_storage.py` | MODIFY | Update storage tests for `form_uid`, add `load_by_slug` tests |
| `packages/parrot-formdesigner/tests/test_handlers.py` | MODIFY | Update API URL paths, add blank form and UUID validation tests |
| `packages/parrot-formdesigner/tests/test_submissions.py` | MODIFY | Update submission tests for `form_uid` |
| `packages/parrot-formdesigner/tests/test_blob_storage.py` | MODIFY | Update blob tests for `form_uid` key pattern |
| `packages/parrot-formdesigner/tests/test_create_form.py` | MODIFY | Update CreateFormTool tests for `form_uid` |
| `packages/parrot-formdesigner/tests/test_operations.py` | MODIFY | Update operations tests for `form_uid` |
| `packages/parrot-formdesigner/tests/test_form_uid_integration.py` | CREATE | New integration test file for cross-module `form_uid` flows |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pytest                          # verified: used in all test files
import uuid                            # stdlib
from parrot_formdesigner.core.schema import FormSchema      # verified
from parrot_formdesigner.services.registry import FormRegistry  # verified
from parrot_formdesigner.services.storage import PostgresFormStorage  # verified
from parrot_formdesigner.services.submissions import FormSubmission  # verified
from parrot_formdesigner.services.blob_storage import BlobMetadata  # verified
```

### Existing Test Structure
```
packages/parrot-formdesigner/tests/
    conftest.py          # shared fixtures
    test_schema.py       # FormSchema unit tests
    test_registry.py     # FormRegistry tests
    test_storage.py      # PostgresFormStorage tests (may need DB)
    test_handlers.py     # API handler tests (aiohttp test client)
    test_submissions.py  # FormSubmission tests
    test_blob_storage.py # BlobStorage tests
    test_create_form.py  # CreateFormTool tests
    test_operations.py   # Operations endpoint tests
```

### Does NOT Exist
- ~~Tests for `form_uid` field~~ — no existing tests reference `form_uid`.
- ~~Tests for `get_by_slug()`~~ — method does not exist before TASK-1973.
- ~~Tests for `tenant_form_slug` index~~ — index does not exist before TASK-1973.
- ~~Tests for `create_blank_form` endpoint~~ — endpoint does not exist before TASK-1976.
- ~~Tests for UUID validation (400 response)~~ — no validation exists before TASK-1976.
- ~~`test_form_uid_integration.py`~~ — does not exist. This task creates it.

---

## Implementation Notes

### Fixture update pattern
```python
# conftest.py — update form fixture to include form_uid
@pytest.fixture
def sample_form_schema():
    return FormSchema(
        form_uid="550e8400-e29b-41d4-a716-446655440000",  # ADD THIS
        form_id="test-form",
        version="1.0",
        title={"en": "Test Form"},
        # ... other fields
    )
```

### API URL update pattern
```python
# BEFORE:
resp = await client.get("/api/v1/forms/test-form")
# AFTER:
resp = await client.get("/api/v1/forms/550e8400-e29b-41d4-a716-446655440000")
```

### Integration test structure
```python
# test_form_uid_integration.py
"""
Cross-module integration tests for form_uid stability.

Tests the full lifecycle:
1. Create form (gets form_uid)
2. Register in registry (keyed by form_uid)
3. Save to storage (keyed by form_uid)
4. Access via API (path uses form_uid)
5. Rename slug (form_id changes, form_uid stays)
6. Verify all access still works via form_uid
"""
```

### Key Constraints
- Some test files may not exist yet if they were not needed before. Check
  existence before modifying; create if needed.
- Integration tests requiring a database should be marked with
  `@pytest.mark.integration` or `@pytest.mark.asyncio` as appropriate.
- Do NOT modify implementation code — this task is test-only.

---

## Acceptance Criteria

- [ ] All existing test fixtures include `form_uid` where applicable
- [ ] All API test URLs use `form_uid` instead of `form_id`
- [ ] New test: blank form creation (`POST /forms/blank`)
- [ ] New test: slug search (`GET /forms?slug=...`)
- [ ] New test: UUID validation returns 400 on invalid UUID
- [ ] New test: form rename does not change `form_uid`
- [ ] New test: registry dual-index (`_slug_index` maps to `form_uid`)
- [ ] New test: slug uniqueness per tenant enforcement
- [ ] New test: storage migration integrity (all rows have `form_uid`)
- [ ] New test: migration script idempotency (rerun without errors)
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/ -v`
- [ ] No implementation code was modified (test-only changes)

---

## Test Specification
```python
import pytest
import uuid as _uuid

# --- Blank form creation ---
@pytest.mark.asyncio
async def test_create_blank_form_returns_uid(client):
    """POST /forms/blank returns form_uid in response."""
    resp = await client.post("/api/v1/forms/blank")
    assert resp.status in (200, 201)
    body = await resp.json()
    assert "form_uid" in body
    _uuid.UUID(body["form_uid"])  # Valid UUID

# --- Slug search ---
@pytest.mark.asyncio
async def test_list_forms_filter_by_slug(client, registered_form):
    """GET /forms?slug=test-form returns matching forms."""
    resp = await client.get("/api/v1/forms?slug=test-form")
    assert resp.status == 200
    body = await resp.json()
    assert len(body) >= 1

# --- UUID validation ---
@pytest.mark.asyncio
async def test_invalid_uuid_returns_400(client):
    """GET /forms/not-a-uuid returns 400 JSON error."""
    resp = await client.get("/api/v1/forms/not-a-uuid")
    assert resp.status == 400
    body = await resp.json()
    assert "error" in body

# --- Rename stability ---
@pytest.mark.asyncio
async def test_form_rename_preserves_uid(registry):
    """Changing form_id does not change form_uid."""
    schema = FormSchema(form_uid="uid-001", form_id="old-slug", ...)
    registry.register(schema)
    schema.form_id = "new-slug"
    registry.register(schema)  # Re-register with new slug
    loaded = registry.get("uid-001")
    assert loaded.form_uid == "uid-001"
    assert loaded.form_id == "new-slug"

# --- Dual index ---
def test_registry_slug_index(registry):
    """Slug index maps tenant_form_slug to form_uid."""
    schema = FormSchema(form_uid="uid-002", form_id="my-form", ...)
    registry.register(schema, tenant="default")
    result = registry.get_by_slug("my-form", tenant="default")
    assert result.form_uid == "uid-002"

# --- Slug uniqueness ---
def test_slug_uniqueness_per_tenant(registry):
    """Two different form_uids cannot share the same slug in one tenant."""
    schema1 = FormSchema(form_uid="uid-003", form_id="shared-slug", ...)
    schema2 = FormSchema(form_uid="uid-004", form_id="shared-slug", ...)
    registry.register(schema1, tenant="default")
    with pytest.raises(Exception):  # Slug conflict
        registry.register(schema2, tenant="default")

# --- Migration integrity ---
@pytest.mark.integration
@pytest.mark.asyncio
async def test_migration_001_backfills_form_uid(db_connection):
    """After 001_add_form_uid.sql, all rows have non-null form_uid."""
    rows = await db_connection.fetch(
        "SELECT id, form_uid FROM form_schemas WHERE form_uid IS NULL"
    )
    assert len(rows) == 0

# --- Migration idempotency ---
@pytest.mark.integration
@pytest.mark.asyncio
async def test_migration_001_idempotent(db_connection):
    """Running 001 twice produces no errors."""
    # Execute migration SQL twice — second run should be no-op
    pass
```

---

## Agent Instructions

1. Read this task file and the spec (Module 10).
2. Verify ALL prior tasks (TASK-1972 through TASK-1981) are complete.
3. List all test files in `packages/parrot-formdesigner/tests/`.
4. Read each test file to understand current test patterns and fixtures.
5. Update `conftest.py` fixtures first (other tests depend on them).
6. Update each test file to use `form_uid` where applicable.
7. Create `test_form_uid_integration.py` with cross-module tests.
8. Run the full test suite: `pytest packages/parrot-formdesigner/tests/ -v`
9. Fix any test failures (test code only, not implementation).
10. Commit with message: `sdd: TASK-1982 — comprehensive form_uid test coverage`
11. Update this task status to `done`.

---

## Completion Note
*(Agent fills this in when done)*
