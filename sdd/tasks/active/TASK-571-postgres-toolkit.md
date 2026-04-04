# TASK-571: PostgresToolkit — PostgreSQL-Specific Overrides

**Feature**: sqlagent-repair
**Spec**: `sdd/specs/sqlagent-repair.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-570
**Assigned-to**: unassigned

---

## Context

Implements spec Module 4. `PostgresToolkit` overrides `SQLToolkit` dialect hooks for PostgreSQL-specific behavior: `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`, `pg_class`/`pg_namespace` joins for schema introspection, `postgresql+asyncpg://` driver mapping. Absorbs the full `PgSchemaSearchTool.analyze_table()` logic from `parrot_tools/database/pg.py`.

---

## Scope

- Implement `PostgresToolkit(SQLToolkit)` in `toolkits/postgres.py`
- Override dialect hooks:
  - `_get_explain_prefix()` → `"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)"`
  - `_get_information_schema_query()` → uses `pg_class`/`pg_namespace` joins with `obj_description()` for comments
  - `_get_columns_query()` → uses `information_schema.columns` + `col_description()` for column comments
  - `_get_primary_keys_query()` → uses `information_schema.key_column_usage` + `table_constraints`
  - `_build_dsn()` → ensures `postgresql+asyncpg://` prefix
  - `_get_sample_data_query()` → `SELECT * FROM "schema"."table" LIMIT N`
- Port `analyze_table()` logic from `PgSchemaSearchTool` (pg.py:243-343) into the schema search flow
- Port `analyze_schema()` logic from `PgSchemaSearchTool` (pg.py:201-241)
- Write unit tests

**NOT in scope**: BigQuery, InfluxDB, Elasticsearch, DocumentDB toolkits. Agent integration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/database/toolkits/postgres.py` | CREATE | PostgresToolkit implementation |
| `parrot/bots/database/toolkits/__init__.py` | MODIFY | Add PostgresToolkit export |
| `tests/unit/test_postgres_toolkit.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Parent class (TASK-570 output)
from parrot.bots.database.toolkits.sql import SQLToolkit

# Models
from parrot.bots.database.models import TableMetadata  # models.py:104
```

### Existing Signatures to Use
```python
# parrot_tools/database/pg.py:243 — ABSORB this logic
# async def analyze_table(self, session, schema_name, table_name, table_type, comment) -> TableMetadata:
#   - Gets columns via information_schema.columns + col_description()
#   - Gets primary keys via key_column_usage + table_constraints
#   - Gets row count via pg_class.reltuples
#   - Gets sample data via SELECT * LIMIT 3
#   - Returns TableMetadata dataclass

# parrot_tools/database/pg.py:201 — ABSORB this logic
# async def analyze_schema(self, schema_name) -> int:
#   - Gets all tables via information_schema.tables with pg_class join
#   - Calls analyze_table() for each
#   - Stores in metadata_cache
```

### Does NOT Exist
- ~~`PostgresToolkit`~~ — does not exist yet (this task creates it)
- ~~`SQLToolkit._analyze_table()`~~ — not on the base class; only PG needs pg_class joins
- ~~`SQLToolkit.analyze_schema()`~~ — not on the base class; schema analysis is toolkit-specific

---

## Implementation Notes

### Key Constraints
- PostgreSQL-specific SQL uses `pg_class`, `pg_namespace`, `obj_description()`, `col_description()` — these are PG-only system functions
- DSN must be `postgresql+asyncpg://` for sqlalchemy backend, or driver `'pg'` for asyncdb
- Sample data query must quote schema and table names: `"schema"."table"`
- Row count uses `reltuples::bigint` estimate from `pg_class` (not `COUNT(*)`)

### References in Codebase
- `parrot_tools/database/pg.py:243-343` — full `analyze_table()` implementation to port
- `parrot_tools/database/pg.py:114-199` — `_search_in_database()` with PG-specific SQL
- `parrot/bots/database/sql.py:34-45` — `_ensure_async_driver()` for DSN rewriting

---

## Acceptance Criteria

- [ ] `PostgresToolkit` inherits from `SQLToolkit`
- [ ] `_get_explain_prefix()` returns `"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)"`
- [ ] Schema introspection uses `pg_class`/`pg_namespace` joins
- [ ] Column metadata includes `col_description()` comments
- [ ] `_build_dsn()` ensures `postgresql+asyncpg://` prefix
- [ ] All tests pass: `pytest tests/unit/test_postgres_toolkit.py -v`
- [ ] Imports work: `from parrot.bots.database.toolkits import PostgresToolkit`

---

## Test Specification

```python
import pytest
from parrot.bots.database.toolkits.postgres import PostgresToolkit


class TestPostgresToolkit:
    def test_explain_prefix(self):
        tk = PostgresToolkit(dsn="postgresql://test", backend="asyncdb")
        assert tk._get_explain_prefix() == "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)"

    def test_build_dsn_asyncpg(self):
        tk = PostgresToolkit(dsn="postgresql://user:pass@host/db", backend="sqlalchemy")
        result = tk._build_dsn("postgresql://user:pass@host/db")
        assert "asyncpg" in result

    def test_build_dsn_already_async(self):
        tk = PostgresToolkit(dsn="postgresql+asyncpg://test", backend="sqlalchemy")
        result = tk._build_dsn("postgresql+asyncpg://test")
        assert result == "postgresql+asyncpg://test"

    def test_inherits_sql_toolkit(self):
        from parrot.bots.database.toolkits.sql import SQLToolkit
        assert issubclass(PostgresToolkit, SQLToolkit)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/sqlagent-repair.spec.md` (Module 4)
2. **Check dependencies** — verify TASK-570 is completed
3. **Read `parrot_tools/database/pg.py`** — this is the primary source to port from
4. **Implement** following the scope above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
