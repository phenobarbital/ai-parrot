# TASK-570: SQLToolkit — Common SQL Operations

**Feature**: sqlagent-repair
**Spec**: `sdd/specs/sqlagent-repair.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-569
**Assigned-to**: unassigned

---

## Context

Implements spec Module 3. `SQLToolkit` is the shared base for all SQL-dialect databases (PostgreSQL, BigQuery, MySQL, etc.). It implements `search_schema()`, `generate_query()`, `execute_query()`, `explain_query()`, and `validate_query()` with overridable hooks for dialect differences. Supports both asyncdb and sqlalchemy-async backends via `backend` config.

---

## Scope

- Implement `SQLToolkit(DatabaseToolkit)` in `toolkits/sql.py`
- **Connection management**:
  - `start()`: connect via asyncdb (`AsyncDB(driver, dsn=dsn)`) or sqlalchemy (`create_async_engine()`) based on `backend` config
  - `stop()`: close connections
- **Schema operations**:
  - `search_schema(search_term, schema_name, table_name, search_type, limit)` — uses information_schema queries; caches results in `CachePartition`
  - Port search-in-database logic from `PgSchemaSearchTool._search_in_database()` (parrot_tools/database/pg.py:114)
- **Query operations**:
  - `generate_query(natural_language, target_tables, query_type)` — returns SQL string (LLM-assisted; method provides schema context, actual generation is by the LLM calling this tool)
  - `execute_query(query, limit, timeout, schema_name)` → `QueryExecutionResponse`
  - `explain_query(query)` — runs `{_get_explain_prefix()} {query}` and returns plan text
  - `validate_query(sql)` — checks SQL syntax and referenced tables exist
- **Overridable dialect hooks** (called by the above methods):
  - `_get_explain_prefix()` → `"EXPLAIN ANALYZE"` (default)
  - `_get_information_schema_query(search_term, schemas)` → SQL string for table discovery
  - `_get_columns_query(schema, table)` → SQL for column metadata
  - `_get_primary_keys_query(schema, table)` → SQL for PK lookup
  - `_build_dsn(raw_dsn)` → ensure async driver in DSN
  - `_get_sample_data_query(schema, table, limit)` → SQL for sample rows
- Write unit tests with mock database connections

**NOT in scope**: PostgreSQL-specific overrides (TASK-571), BigQuery-specific overrides (TASK-572), non-SQL databases, agent integration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/database/toolkits/sql.py` | CREATE | SQLToolkit implementation |
| `parrot/bots/database/toolkits/__init__.py` | MODIFY | Add SQLToolkit export |
| `tests/unit/test_sql_toolkit.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Parent class (TASK-569 output)
from parrot.bots.database.toolkits.base import DatabaseToolkit

# Cache (TASK-568 output)
from parrot.bots.database.cache import CachePartition

# Models
from parrot.bots.database.models import TableMetadata          # models.py:104
from parrot.bots.database.models import SchemaMetadata         # models.py:84
from parrot.bots.database.models import QueryExecutionResponse # models.py:180
from parrot.bots.database.models import QueryExecutionRequest  # models.py:170

# Retry
from parrot.bots.database.retries import QueryRetryConfig, SQLRetryHandler  # retries.py:6,31

# External
from asyncdb import AsyncDB                                     # external
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
```

### Existing Signatures to Use
```python
# parrot_tools/database/pg.py:114 — reference for database search logic
# async def _search_in_database(self, search_term, schema_name, table_name, search_type, limit):
#   Uses information_schema.tables with ILIKE pattern matching

# parrot_tools/database/pg.py:243 — reference for table analysis
# async def analyze_table(self, session, schema_name, table_name, table_type, comment) -> TableMetadata:
#   Gets columns, primary keys, row count, sample data

# parrot/bots/database/retries.py:31
class SQLRetryHandler:
    def __init__(self, agent, config=None):            # line 34
    def _is_retryable_error(self, error) -> bool:      # line 39

# parrot_tools/querytoolkit.py:146 — asyncdb connection pattern
# def _get_driver(self) -> AsyncDB:
#     self._db = AsyncDB(self.driver, dsn=self.default_dsn, params=self.credentials)
```

### Does NOT Exist
- ~~`SQLToolkit`~~ — does not exist yet (this task creates it)
- ~~`DatabaseToolkit.execute_raw_sql()`~~ — no such method on base class
- ~~`AsyncDB.execute()`~~ — asyncdb uses `connection.query()` not `execute()`
- ~~`QueryToolkit.search_schema()`~~ — QueryToolkit has no schema search

---

## Implementation Notes

### Pattern to Follow
```python
class SQLToolkit(DatabaseToolkit):
    """Common SQL operations with overridable dialect hooks."""

    exclude_tools = ('start', 'stop', 'cleanup', 'get_table_metadata',
                     '_get_explain_prefix', '_get_information_schema_query',
                     '_get_columns_query', '_get_primary_keys_query',
                     '_build_dsn', '_get_sample_data_query')

    async def start(self) -> None:
        """Connect to database."""
        if self.backend == "asyncdb":
            self._db = AsyncDB(self.driver, dsn=self.dsn, params=self.credentials)
        else:
            connection_string = self._build_dsn(self.dsn)
            self.engine = create_async_engine(connection_string, ...)
            self.session_maker = sessionmaker(self.engine, class_=AsyncSession, ...)

    async def search_schema(self, search_term: str, ...) -> List[TableMetadata]:
        """Search for tables/columns matching the search term."""
        # 1. Check cache partition first
        # 2. If miss, query information_schema via _get_information_schema_query()
        # 3. Store results in cache
        ...
```

### Key Constraints
- asyncdb pattern: `async with await self._db.connection() as conn: result, error = await conn.query(sql)`
- sqlalchemy pattern: `async with self.session_maker() as session: result = await session.execute(text(sql))`
- All `_get_*` hook methods are NOT async (they return SQL strings, not results)
- Private methods starting with `_` are automatically excluded from tool generation by AbstractToolkit

### References in Codebase
- `parrot_tools/database/pg.py` — full reference for schema search + table analysis
- `parrot_tools/querytoolkit.py:146` — asyncdb connection pattern
- `parrot/bots/database/abstract.py:195-236` — sqlalchemy connection pattern
- `parrot/bots/db/sql.py:616-820` — query generation/execution logic to port

---

## Acceptance Criteria

- [ ] `SQLToolkit` inherits from `DatabaseToolkit`
- [ ] `search_schema()` returns `List[TableMetadata]` with cache-first strategy
- [ ] `execute_query()` returns `QueryExecutionResponse` via asyncdb or sqlalchemy
- [ ] `explain_query()` uses `_get_explain_prefix()` hook
- [ ] `_build_dsn()` ensures async driver
- [ ] Backend selection (`asyncdb` vs `sqlalchemy`) works correctly
- [ ] All tests pass: `pytest tests/unit/test_sql_toolkit.py -v`
- [ ] Imports work: `from parrot.bots.database.toolkits import SQLToolkit`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.bots.database.toolkits.sql import SQLToolkit
from parrot.bots.database.models import QueryExecutionResponse


class TestSQLToolkit:
    def test_tool_methods_exposed(self):
        """SQL methods become LLM-callable tools."""
        tk = SQLToolkit(dsn="postgresql://test", backend="asyncdb")
        tool_names = [t.name for t in tk.get_tools()]
        assert "search_schema" in tool_names
        assert "generate_query" in tool_names
        assert "execute_query" in tool_names
        assert "explain_query" in tool_names
        assert "validate_query" in tool_names

    def test_dialect_hooks_not_exposed(self):
        """Private dialect hooks are not LLM tools."""
        tk = SQLToolkit(dsn="postgresql://test", backend="asyncdb")
        tool_names = [t.name for t in tk.get_tools()]
        assert "_get_explain_prefix" not in tool_names
        assert "_build_dsn" not in tool_names

    def test_default_explain_prefix(self):
        """Default explain prefix is EXPLAIN ANALYZE."""
        tk = SQLToolkit(dsn="postgresql://test", backend="asyncdb")
        assert "EXPLAIN" in tk._get_explain_prefix()

    def test_backend_selection(self):
        """Backend config is stored correctly."""
        tk1 = SQLToolkit(dsn="postgresql://test", backend="asyncdb")
        tk2 = SQLToolkit(dsn="postgresql://test", backend="sqlalchemy")
        assert tk1.backend == "asyncdb"
        assert tk2.backend == "sqlalchemy"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/sqlagent-repair.spec.md` (Module 3)
2. **Check dependencies** — verify TASK-569 is completed (DatabaseToolkit base exists)
3. **Read reference code**: `parrot_tools/database/pg.py` for schema search patterns, `parrot_tools/querytoolkit.py` for asyncdb patterns
4. **Verify the Codebase Contract** — confirm all listed imports still exist
5. **Implement** following the scope above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
