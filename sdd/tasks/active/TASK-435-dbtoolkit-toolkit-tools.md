# TASK-435: DatabaseToolkit — Tools, Schemas & Package Init

**Feature**: DatabaseToolkit
**Feature ID**: FEAT-062
**Spec**: `sdd/specs/databasetoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-427, TASK-428, TASK-429, TASK-430, TASK-431, TASK-432, TASK-433, TASK-434
**Assigned-to**: unassigned

---

## Context

This is the main orchestration task. It implements the four `AbstractTool` subclasses
that LLMs interact with, the argument schemas, the `DatabaseToolkit` class that ties
everything together, and the package `__init__.py` that provides clean public exports.

Implements **Modules 8 and 9** from the spec.

---

## Scope

### Argument Schemas (Pydantic v2, extending `AbstractToolArgsSchema`)
- `DatabaseBaseArgs` — `driver: str`, `credentials: dict | None`
- `GetMetadataArgs(DatabaseBaseArgs)` — adds `tables: list[str] | None`
- `ValidateQueryArgs(DatabaseBaseArgs)` — adds `query: str`
- `ExecuteQueryArgs(DatabaseBaseArgs)` — adds `query: str`, `params: dict | None`
- `FetchRowArgs(DatabaseBaseArgs)` — adds `query: str`, `params: dict | None`

### Tool Implementations (each inherits `AbstractTool`)
- `GetDatabaseMetadataTool` — name: `"get_database_metadata"`
- `ValidateDatabaseQueryTool` — name: `"validate_database_query"`
- `ExecuteDatabaseQueryTool` — name: `"execute_database_query"`
- `FetchDatabaseRowTool` — name: `"fetch_database_row"`

Each tool's `_execute()`:
1. Normalizes the driver name via `normalize_driver()`
2. Gets the source via `self._toolkit.get_source(driver)`
3. Resolves credentials via `source.resolve_credentials(credentials)`
4. Delegates to the appropriate source method
5. Wraps result in `ToolResult`

### DatabaseToolkit Class
- `__init__()` — creates logger, initializes 4 tools, empty source cache
- `get_source(driver)` — lazy-instantiate and cache source
- `get_tools()` → `list[AbstractTool]`
- `get_tool_by_name(name)` → `AbstractTool | None`
- `cleanup()` — clear source cache

### Package Init
- `parrot/tools/database/__init__.py` — export `DatabaseToolkit`,
  `AbstractDatabaseSource`, all result types.

**NOT in scope**: Source implementations (previous tasks), tests (TASK-436).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/database/toolkit.py` | CREATE | Schemas, tools, DatabaseToolkit |
| `parrot/tools/database/__init__.py` | MODIFY | Add public exports |

---

## Implementation Notes

### Pattern to Follow
```python
# toolkit.py
import logging
import contextlib
from typing import Any
from pydantic import Field
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema, ToolResult
from parrot.tools.database.base import (
    AbstractDatabaseSource, MetadataResult, ValidationResult,
    QueryResult, RowResult,
)
from parrot.tools.database.sources import get_source_class, normalize_driver


class DatabaseBaseArgs(AbstractToolArgsSchema):
    driver: str = Field(
        description=(
            "Database driver. Supported: 'pg' (PostgreSQL), 'mysql', 'sqlite', "
            "'bigquery', 'mssql', 'oracle', 'clickhouse', 'duckdb', "
            "'mongo' (MongoDB), 'atlas', 'documentdb', 'influx' (InfluxDB), "
            "'elastic' (Elasticsearch/OpenSearch). Aliases accepted."
        )
    )
    credentials: dict[str, Any] | None = Field(
        default=None,
        description="Optional connection credentials. If omitted, defaults are used."
    )


class GetDatabaseMetadataTool(AbstractTool):
    name = "get_database_metadata"
    description = (
        "Discover the schema of a database: list tables, collections, or measurements "
        "and their column/field definitions. Call this BEFORE writing any query."
    )
    args_schema = GetMetadataArgs

    def __init__(self, toolkit_ref: "DatabaseToolkit"):
        super().__init__()
        self._toolkit = toolkit_ref

    async def _execute(self, **kwargs) -> ToolResult:
        driver = normalize_driver(kwargs["driver"])
        source = self._toolkit.get_source(driver)
        creds = await source.resolve_credentials(kwargs.get("credentials"))
        result = await source.get_metadata(creds, kwargs.get("tables"))
        return ToolResult(success=True, result=result.model_dump())


class DatabaseToolkit:
    def __init__(self):
        self.logger = logging.getLogger("Parrot.Toolkits.Database")
        self._tools: list[AbstractTool] = []
        self._source_cache: dict[str, AbstractDatabaseSource] = {}
        self._initialize_tools()

    def _initialize_tools(self):
        self._tools = [
            GetDatabaseMetadataTool(toolkit_ref=self),
            ValidateDatabaseQueryTool(toolkit_ref=self),
            ExecuteDatabaseQueryTool(toolkit_ref=self),
            FetchDatabaseRowTool(toolkit_ref=self),
        ]

    def get_source(self, driver: str) -> AbstractDatabaseSource:
        canonical = normalize_driver(driver)
        if canonical not in self._source_cache:
            source_cls = get_source_class(canonical)
            self._source_cache[canonical] = source_cls()
        return self._source_cache[canonical]

    def get_tools(self) -> list[AbstractTool]:
        return self._tools

    def get_tool_by_name(self, name: str) -> AbstractTool | None:
        return next((t for t in self._tools if t.name == name), None)

    async def cleanup(self):
        for tool in self._tools:
            with contextlib.suppress(Exception):
                await tool.cleanup()
        self._source_cache.clear()
```

### Key Constraints
- Each tool must have a clear, unambiguous `description` — this becomes the LLM's
  tool description and is critical for correct tool selection
- `_execute()` must return `ToolResult` (from `parrot.tools.abstract`)
- Error handling in `_execute()`: catch exceptions and return
  `ToolResult(success=False, error=str(e))`
- `DatabaseToolkit` is NOT an `AbstractToolkit` — it's a plain class that
  provides `get_tools()`. This matches the spec's design.
- Tool descriptions should guide the three-step flow:
  1. metadata description says "call BEFORE writing any query"
  2. validate description says "call AFTER writing a query and BEFORE executing"
  3. execute description says "call AFTER validate returns valid=True"

### References in Codebase
- `parrot/tools/abstract.py` — `AbstractTool`, `ToolResult`, `AbstractToolArgsSchema`
- `parrot/tools/dataset_manager/tool.py` — toolkit pattern (though it uses AbstractToolkit)
- Spec section 6.2 — tool implementations with descriptions

---

## Acceptance Criteria

- [ ] `DatabaseToolkit().get_tools()` returns exactly 4 tools
- [ ] Tool names: `get_database_metadata`, `validate_database_query`,
      `execute_database_query`, `fetch_database_row`
- [ ] Each tool's `get_schema()` produces valid JSON schema
- [ ] `get_source()` returns and caches source instances
- [ ] `get_source()` with same driver returns cached instance
- [ ] `get_tool_by_name("get_database_metadata")` returns correct tool
- [ ] `cleanup()` clears source cache
- [ ] Package exports work: `from parrot.tools.database import DatabaseToolkit`
- [ ] Package exports work: `from parrot.tools.database import AbstractDatabaseSource`
- [ ] Package exports work: `from parrot.tools.database import QueryResult, MetadataResult`

---

## Test Specification

```python
# tests/tools/database/test_toolkit.py
import pytest
from parrot.tools.database import DatabaseToolkit
from parrot.tools.database.toolkit import (
    DatabaseBaseArgs, GetMetadataArgs, ValidateQueryArgs,
    ExecuteQueryArgs, FetchRowArgs,
)


class TestDatabaseToolkit:
    def test_get_tools_count(self):
        tk = DatabaseToolkit()
        tools = tk.get_tools()
        assert len(tools) == 4

    def test_tool_names(self):
        tk = DatabaseToolkit()
        names = {t.name for t in tk.get_tools()}
        assert names == {
            "get_database_metadata",
            "validate_database_query",
            "execute_database_query",
            "fetch_database_row",
        }

    def test_get_tool_by_name(self):
        tk = DatabaseToolkit()
        tool = tk.get_tool_by_name("validate_database_query")
        assert tool is not None
        assert tool.name == "validate_database_query"

    def test_get_tool_by_name_not_found(self):
        tk = DatabaseToolkit()
        assert tk.get_tool_by_name("nonexistent") is None

    def test_get_source_caches(self):
        tk = DatabaseToolkit()
        src1 = tk.get_source("pg")
        src2 = tk.get_source("pg")
        assert src1 is src2

    def test_get_source_alias_resolves(self):
        tk = DatabaseToolkit()
        src1 = tk.get_source("postgresql")
        src2 = tk.get_source("pg")
        assert src1 is src2

    def test_tool_schemas_valid(self):
        tk = DatabaseToolkit()
        for tool in tk.get_tools():
            schema = tool.get_schema()
            assert "name" in schema
            assert "description" in schema

    @pytest.mark.asyncio
    async def test_cleanup(self):
        tk = DatabaseToolkit()
        _ = tk.get_source("pg")
        assert len(tk._source_cache) > 0
        await tk.cleanup()
        assert len(tk._source_cache) == 0


class TestArgSchemas:
    def test_database_base_args(self):
        args = DatabaseBaseArgs(driver="pg")
        assert args.driver == "pg"
        assert args.credentials is None

    def test_get_metadata_args(self):
        args = GetMetadataArgs(driver="pg", tables=["users"])
        assert args.tables == ["users"]

    def test_validate_query_args(self):
        args = ValidateQueryArgs(driver="pg", query="SELECT 1")
        assert args.query == "SELECT 1"

    def test_execute_query_args(self):
        args = ExecuteQueryArgs(driver="pg", query="SELECT 1", params={"id": 1})
        assert args.params == {"id": 1}

    def test_fetch_row_args(self):
        args = FetchRowArgs(driver="pg", query="SELECT 1")
        assert args.query == "SELECT 1"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/databasetoolkit.spec.md` for full context
2. **Check dependencies** — ALL source tasks (TASK-427 through TASK-434) must be completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-435-dbtoolkit-toolkit-tools.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
