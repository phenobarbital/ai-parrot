# TASK-529: PostgreSQL Form Storage

**Feature**: form-abstraction-layer
**Spec**: `sdd/specs/form-abstraction-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-518, TASK-527
**Assigned-to**: unassigned

---

## Context

Implements Module 12 from the spec. Implements `FormStorage` ABC using asyncpg for PostgreSQL persistence. Creates the `form_schemas` table via raw SQL. This enables `persistence=True` in the `FormRegistry` — forms survive process restarts.

---

## Scope

- Implement `parrot/forms/storage.py` with `PostgresFormStorage`
- Implement `FormStorage` ABC (defined in TASK-527, but implement here if not already in registry.py)
- Table schema: `form_schemas(id UUID PRIMARY KEY, form_id VARCHAR UNIQUE, version VARCHAR, schema_json JSONB, style_json JSONB, created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ, created_by VARCHAR)`
- Raw SQL for table creation (no Alembic)
- CRUD operations: `save()`, `load()`, `delete()`, `list_forms()`
- Use `FormSchema.model_dump()` for serialization, `FormSchema.model_validate()` for deserialization
- Support versioning: multiple versions of same form_id stored, latest returned by default
- Write unit tests (with mock/fixture for asyncpg connection)

**NOT in scope**: Redis caching (TASK-528), registry core logic (TASK-527), Alembic migrations.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/forms/storage.py` | CREATE | PostgresFormStorage implementation |
| `packages/ai-parrot/src/parrot/forms/__init__.py` | MODIFY | Export PostgresFormStorage |
| `packages/ai-parrot/tests/unit/forms/test_storage.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

```python
class PostgresFormStorage(FormStorage):
    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS form_schemas (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        form_id VARCHAR(255) NOT NULL,
        version VARCHAR(50) NOT NULL DEFAULT '1.0',
        schema_json JSONB NOT NULL,
        style_json JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        created_by VARCHAR(255),
        UNIQUE(form_id, version)
    );
    """

    def __init__(self, pool: asyncpg.Pool): ...
    async def initialize(self) -> None:
        """Create table if not exists."""
    async def save(self, form: FormSchema, style: StyleSchema | None = None) -> str: ...
    async def load(self, form_id: str, version: str | None = None) -> FormSchema | None: ...
    async def delete(self, form_id: str) -> bool: ...
    async def list_forms(self) -> list[dict[str, str]]: ...
```

### Key Constraints
- Use asyncpg connection pool (passed in constructor)
- `save()` uses UPSERT (INSERT ... ON CONFLICT UPDATE) for form_id+version
- `load()` without version returns the latest version (ORDER BY updated_at DESC LIMIT 1)
- JSON serialization: `json.dumps(form.model_dump())` for JSONB columns
- JSON deserialization: `FormSchema.model_validate(json.loads(row['schema_json']))`
- `initialize()` must be called once to create the table (idempotent)

### References in Codebase
- `parrot/vectorstores/pgvector.py` — asyncpg usage pattern in the project

---

## Acceptance Criteria

- [ ] Table created via raw SQL (idempotent)
- [ ] Save, load, delete, list operations work
- [ ] Versioning: multiple versions stored, latest returned by default
- [ ] Specific version loadable
- [ ] UPSERT on save (no duplicate errors)
- [ ] JSON roundtrip preserves FormSchema fidelity
- [ ] Import works: `from parrot.forms import PostgresFormStorage`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/forms/test_storage.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/forms/test_storage.py
import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from parrot.forms import FormSchema, FormField, FormSection, FieldType
from parrot.forms.storage import PostgresFormStorage


@pytest.fixture
def mock_pool():
    pool = AsyncMock()
    pool.acquire = AsyncMock()
    return pool


@pytest.fixture
def storage(mock_pool):
    return PostgresFormStorage(pool=mock_pool)


@pytest.fixture
def sample_form():
    return FormSchema(
        form_id="persist-test", title="Persist Test", version="1.0",
        sections=[FormSection(section_id="s", fields=[
            FormField(field_id="f", field_type=FieldType.TEXT, label="F")
        ])],
    )


class TestPostgresFormStorage:
    async def test_save_calls_execute(self, storage, sample_form, mock_pool):
        conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        await storage.save(sample_form)
        conn.execute.assert_called_once()

    def test_create_table_sql_valid(self, storage):
        assert "CREATE TABLE IF NOT EXISTS" in storage.CREATE_TABLE_SQL
        assert "form_id" in storage.CREATE_TABLE_SQL
        assert "schema_json JSONB" in storage.CREATE_TABLE_SQL
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-abstraction-layer.spec.md` for full context
2. **Check dependencies** — verify TASK-518 and TASK-527 are in `tasks/completed/`
3. **Read** `parrot/vectorstores/pgvector.py` for asyncpg usage patterns
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-529-postgres-form-storage.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-04-03
**Notes**: PostgresFormStorage implementing FormStorage ABC with asyncpg pool. CREATE_TABLE_SQL with UUID, JSONB, UNIQUE(form_id, version). UPSERT_SQL with ON CONFLICT DO UPDATE. save/load/delete/list_forms with proper JSON serialization. versioning via ORDER BY updated_at DESC LIMIT 1 for latest. 15 tests pass using AsyncMock pool fixtures.

**Deviations from spec**: none
