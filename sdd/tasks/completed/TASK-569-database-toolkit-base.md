# TASK-569: DatabaseToolkit Base Class

**Feature**: sqlagent-repair
**Spec**: `sdd/specs/sqlagent-repair.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-568
**Assigned-to**: unassigned

---

## Context

Implements spec Module 2. The `DatabaseToolkit` is the abstract base class that all per-database toolkits inherit from. It bridges `AbstractToolkit` (which auto-generates tools from async methods) with the database-specific contract (connect, search schema, execute queries). It also holds a `CachePartition` and optional `QueryRetryConfig`.

---

## Scope

- Create `parrot/bots/database/toolkits/` subpackage with `__init__.py`
- Implement `DatabaseToolkit(AbstractToolkit, ABC)` in `toolkits/base.py`:
  - Constructor accepts: `dsn`, `allowed_schemas`, `primary_schema`, `backend` ("asyncdb"|"sqlalchemy"), `cache_partition` (from CacheManager), `retry_config`, `database_type`, `**kwargs`
  - Abstract methods: `search_schema()`, `execute_query()`
  - Concrete methods: `start()` (connect), `stop()` (disconnect), `get_table_metadata()` (via cache partition), `cleanup()`
  - `exclude_tools` should include `start`, `stop`, `cleanup`, `get_table_metadata` (internal, not LLM-facing)
- Implement `DatabaseToolkitConfig(BaseModel)` for constructor validation
- Write unit tests verifying tool generation from subclass methods

**NOT in scope**: SQL-specific logic, any concrete database toolkit, agent integration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/database/toolkits/__init__.py` | CREATE | Subpackage init with exports |
| `parrot/bots/database/toolkits/base.py` | CREATE | DatabaseToolkit base class |
| `tests/unit/test_database_toolkit_base.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Toolkit infrastructure
from parrot.tools.toolkit import AbstractToolkit  # parrot/tools/toolkit.py:140

# Cache (created in TASK-568)
from parrot.bots.database.cache import CachePartition, CachePartitionConfig  # TASK-568 output

# Models
from parrot.bots.database.models import TableMetadata    # models.py:104
from parrot.bots.database.models import SchemaMetadata   # models.py:84
from parrot.bots.database.models import QueryExecutionResponse  # models.py:180

# Retry
from parrot.bots.database.retries import QueryRetryConfig  # retries.py:6

# External
from asyncdb import AsyncDB  # external
from pydantic import BaseModel, Field  # external
```

### Existing Signatures to Use
```python
# parrot/tools/toolkit.py:140
class AbstractToolkit(ABC):
    exclude_tools: tuple[str, ...] = ()               # line 177
    def __init__(self, **kwargs):                     # line 179
    def get_tools(self) -> List[ToolkitTool]:         # line 216
    async def start(self) -> None:                    # line 195
    async def stop(self) -> None:                     # line 202
    async def cleanup(self) -> None:                  # line 209
    def _generate_tools(self):                        # line 248
```

### Does NOT Exist
- ~~`parrot.bots.database.toolkits`~~ — subpackage does not exist yet (this task creates it)
- ~~`DatabaseToolkit`~~ — does not exist yet (this task creates it)
- ~~`AbstractToolkit.register_with_agent()`~~ — no such method
- ~~`AbstractToolkit.set_cache()`~~ — no such method; cache is passed via constructor

---

## Implementation Notes

### Pattern to Follow
```python
class DatabaseToolkit(AbstractToolkit, ABC):
    exclude_tools = ('start', 'stop', 'cleanup', 'get_table_metadata')

    def __init__(self, dsn: str, allowed_schemas: List[str] = None, 
                 primary_schema: Optional[str] = None,
                 backend: str = "asyncdb",
                 cache_partition: Optional[CachePartition] = None,
                 retry_config: Optional[QueryRetryConfig] = None,
                 database_type: str = "postgresql",
                 **kwargs):
        super().__init__(**kwargs)
        # Store config, set up connection attributes
        ...

    @abstractmethod
    async def search_schema(self, search_term: str, schema_name: Optional[str] = None,
                           limit: int = 10) -> List[TableMetadata]:
        """Search for tables/columns matching the search term."""
        ...

    @abstractmethod
    async def execute_query(self, query: str, limit: int = 1000,
                           timeout: int = 30) -> QueryExecutionResponse:
        """Execute a query and return results."""
        ...
```

### Key Constraints
- Must call `super().__init__(**kwargs)` to trigger AbstractToolkit initialization
- `exclude_tools` must prevent internal methods from becoming LLM tools
- `backend` field controls whether to use `asyncdb.AsyncDB` or `sqlalchemy.ext.asyncio.create_async_engine`
- Connection is lazy — `start()` connects, constructor only stores config

### References in Codebase
- `parrot/tools/toolkit.py` — AbstractToolkit base class
- `parrot_tools/querytoolkit.py:89` — reference for asyncdb connection pattern (`_get_driver()`)

---

## Acceptance Criteria

- [ ] `DatabaseToolkit` inherits from `AbstractToolkit` and `ABC`
- [ ] Subclass with public async methods generates tools via `get_tools()`
- [ ] `exclude_tools` correctly hides internal methods
- [ ] `start()`/`stop()` lifecycle works
- [ ] All tests pass: `pytest tests/unit/test_database_toolkit_base.py -v`
- [ ] Imports work: `from parrot.bots.database.toolkits import DatabaseToolkit`

---

## Test Specification

```python
import pytest
from parrot.bots.database.toolkits.base import DatabaseToolkit
from parrot.bots.database.models import TableMetadata, QueryExecutionResponse


class MockToolkit(DatabaseToolkit):
    """Concrete subclass for testing."""
    async def search_schema(self, search_term, schema_name=None, limit=10):
        """Search database schema for tables matching the term."""
        return []

    async def execute_query(self, query, limit=1000, timeout=30):
        """Execute a database query."""
        return QueryExecutionResponse(
            success=True, row_count=0, execution_time_ms=0.0,
            schema_used="public"
        )

    async def do_something(self, param: str) -> str:
        """A custom tool method."""
        return f"done: {param}"


class TestDatabaseToolkitBase:
    def test_tool_generation(self):
        """Public async methods become tools."""
        tk = MockToolkit(dsn="postgresql://test", backend="asyncdb")
        tools = tk.get_tools()
        tool_names = [t.name for t in tools]
        assert "search_schema" in tool_names
        assert "execute_query" in tool_names
        assert "do_something" in tool_names

    def test_exclude_tools(self):
        """Internal methods are excluded."""
        tk = MockToolkit(dsn="postgresql://test", backend="asyncdb")
        tool_names = [t.name for t in tk.get_tools()]
        assert "start" not in tool_names
        assert "stop" not in tool_names
        assert "cleanup" not in tool_names
        assert "get_table_metadata" not in tool_names
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/sqlagent-repair.spec.md` for full context
2. **Check dependencies** — verify TASK-568 is completed (CacheManager exists)
3. **Verify the Codebase Contract** — confirm AbstractToolkit still has `exclude_tools` and `_generate_tools()`
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
