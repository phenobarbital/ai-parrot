# TASK-735: Refactor `DatabaseQueryToolkit` as `AbstractToolkit` + DDL guard

**Feature**: databasetoolkit-clash
**Spec**: `sdd/specs/databasetoolkit-clash.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-733
**Assigned-to**: unassigned

---

## Context

After TASK-733, the toolkit lives at
`packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py` but still
follows the FEAT-062 design: a plain class that owns four hand-written
`AbstractTool` subclasses. This task rewrites it as an `AbstractToolkit`
subclass with four public async methods, and wires
`parrot.security.QueryValidator` as the DDL/DML safety net missing today.

Implements **Modules 3 + 5** of the spec.

---

## Scope

- Rename the class `DatabaseToolkit` → `DatabaseQueryToolkit` inside `toolkit.py`.
- Inherit from `parrot.tools.toolkit.AbstractToolkit`.
- Delete the four `AbstractTool` subclasses and their `Args` schemas
  (`GetDatabaseMetadataTool`, `ValidateDatabaseQueryTool`,
  `ExecuteDatabaseQueryTool`, `FetchDatabaseRowTool`,
  `GetMetadataArgs`, `ValidateQueryArgs`, `ExecuteQueryArgs`,
  `FetchRowArgs`, `DatabaseBaseArgs`).
- Add four public async methods on `DatabaseQueryToolkit`:
  - `async def get_database_metadata(self, driver, credentials=None, tables=None) -> dict`
  - `async def validate_database_query(self, driver, query, credentials=None) -> dict`
  - `async def execute_database_query(self, driver, query, credentials=None, params=None) -> dict`
  - `async def fetch_database_row(self, driver, query, credentials=None, params=None) -> dict`
  Each returns `<Result>.model_dump()` (no `ToolResult` wrapping —
  `AbstractToolkit` handles that).
- Add a private module-level mapping
  `_DRIVER_TO_QUERY_LANGUAGE: dict[str, QueryLanguage]` covering all 13
  canonical drivers (see Implementation Notes).
- Inside `validate_database_query`, `execute_database_query`,
  `fetch_database_row`: call
  `QueryValidator.validate_query(query, language)` BEFORE touching the
  source. If the result indicates unsafe (`is_safe=False` or `valid=False`,
  whichever the dispatcher uses — verify), short-circuit with a
  `ValidationResult(valid=False, error=...)` returned via
  `.model_dump()`.
- Set `tool_prefix: str = "db"` (Q2 default per spec).
- Set `exclude_tools: tuple[str, ...] = ("get_source", "cleanup")` so
  internal helpers stay hidden.
- Keep `get_source(self, driver: str) -> AbstractDatabaseSource` and
  `async def cleanup(self) -> None` synchronous/async respectively —
  they're the only non-tool methods kept.
- Update the package `__init__.py` to export `DatabaseQueryToolkit`
  (still keep the old `DatabaseToolkit` re-export — TASK-736 will
  redirect that into a deprecation alias).

**NOT in scope**:
- Adding the `parrot.tools.database.py` deprecation shim (TASK-736).
- Updating `TOOL_REGISTRY` (TASK-737).
- Touching `tool.py` (the legacy DatabaseQueryTool).
- Adding tests (TASK-738).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py` | REWRITE | Class rename, inherit `AbstractToolkit`, public-method tools, DDL guard, driver→language mapping |
| `packages/ai-parrot/src/parrot/tools/databasequery/__init__.py` | MODIFY | Export `DatabaseQueryToolkit` (keep `DatabaseToolkit` re-export for now) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit
# verified: packages/ai-parrot/src/parrot/tools/toolkit.py:140

from parrot.tools.databasequery.base import (
    AbstractDatabaseSource,
    MetadataResult, QueryResult, RowResult, ValidationResult,
)
# verified after TASK-733: same symbols, renamed module path

from parrot.tools.databasequery.sources import get_source_class, normalize_driver
# verified after TASK-733

from parrot.security import QueryLanguage, QueryValidator
# verified: packages/ai-parrot/src/parrot/security/query_validator.py:19,29
# verified re-export: parrot.security.__init__.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py:140
class AbstractToolkit(ABC):
    exclude_tools: tuple[str, ...] = ()                              # line 177
    tool_prefix: Optional[str] = None                                # line 191
    prefix_separator: str = "_"                                      # line 194
    def __init__(self, **kwargs): ...                                # line 196
    async def start(self) -> None: ...                               # line 212
    async def stop(self) -> None: ...                                # line 219
    async def cleanup(self) -> None: ...                             # line 226
    def get_tools(self, permission_context=None, resolver=None) -> List[AbstractTool]: ...  # line 233
    def _generate_tools(self) -> None: ...                           # line 286

# packages/ai-parrot/src/parrot/security/query_validator.py:29
class QueryValidator:
    @staticmethod
    def validate_sql_query(query: str) -> Dict[str, Any]: ...        # line 33 — returns {'is_safe': bool, 'message': str, 'suggestions': [...]}
    @staticmethod
    def validate_flux_query(query: str) -> Dict[str, Any]: ...       # line 79
    # VERIFY before wiring — confirm whether `validate_query(query, language)`
    # dispatcher exists, and whether it returns 'is_safe' or 'valid' key.
    # Read the file end-to-end with `read` before referencing.

# packages/ai-parrot/src/parrot/security/query_validator.py:19
class QueryLanguage(str, Enum):
    SQL = "sql"
    FLUX = "flux"
    MQL = "mql"
    CYPHER = "cypher"
    JSON = "json"
    AQL = "aql"

# packages/ai-parrot/src/parrot/tools/databasequery/base.py (post-TASK-733)
class AbstractDatabaseSource(ABC):
    driver: str
    sqlglot_dialect: str | None = None
    async def resolve_credentials(self, credentials) -> dict: ...
    @abstractmethod
    async def get_default_credentials(self) -> dict: ...
    async def validate_query(self, query: str) -> ValidationResult: ...   # sqlglot syntax
    @abstractmethod
    async def get_metadata(self, credentials, tables=None) -> MetadataResult: ...
    @abstractmethod
    async def query(self, credentials, sql, params=None) -> QueryResult: ...
    @abstractmethod
    async def query_row(self, credentials, sql, params=None) -> RowResult: ...

# packages/ai-parrot/src/parrot/tools/databasequery/sources/__init__.py:45,132 (post-TASK-733)
def normalize_driver(driver: str) -> str: ...
def get_source_class(driver: str) -> type[AbstractDatabaseSource]: ...
```

### Does NOT Exist
- ~~`AbstractToolkit.add_tool(...)` / `register_tool(...)`~~ — tools are
  derived only from public async methods. Use method definitions, not a
  registration call.
- ~~`AbstractToolkit` accepts a `tools=` kwarg~~ — no constructor takes
  pre-built tool instances. Define methods instead.
- ~~`QueryValidator.validate(query)` (no language)~~ — the dispatcher
  signature is `validate_query(query, language)`. Verify presence with
  `grep -n "def validate_query" packages/ai-parrot/src/parrot/security/query_validator.py`. If absent, the toolkit must call `validate_sql_query`/`validate_flux_query` directly based on the resolved `QueryLanguage`.
- ~~`ValidationResult.is_safe` field~~ — `ValidationResult` has `valid`,
  `error`, `dialect`. Map the `QueryValidator` `is_safe`/`message` keys
  into `ValidationResult(valid=..., error=...)` on rejection.
- ~~Synchronous public methods become tools~~ — only `async def` methods
  are picked up by `_generate_tools`. Make `get_source` non-async, list
  it in `exclude_tools`. (Also non-async methods are skipped, but listing
  is defensive and self-documenting.)
- ~~Method docstrings are optional for tool generation~~ — tool
  description comes from the method docstring. Each public method MUST
  have a Google-style docstring.

---

## Implementation Notes

### Pattern to Follow

```python
# parrot/tools/databasequery/toolkit.py (rewritten)
"""DatabaseQueryToolkit — multi-database tools as an AbstractToolkit.

Exposes four LLM-callable tools via public async methods:

  - get_database_metadata
  - validate_database_query
  - execute_database_query
  - fetch_database_row

Every query method routes through ``parrot.security.QueryValidator``
to block DDL/DML before reaching the underlying source.
"""
from __future__ import annotations

import contextlib
import logging
from typing import Any, Optional

from parrot.tools.toolkit import AbstractToolkit
from parrot.security import QueryLanguage, QueryValidator
from parrot.tools.databasequery.base import (
    AbstractDatabaseSource,
    MetadataResult, QueryResult, RowResult, ValidationResult,
)
from parrot.tools.databasequery.sources import get_source_class, normalize_driver


_DRIVER_TO_QUERY_LANGUAGE: dict[str, QueryLanguage] = {
    # SQL family
    "pg": QueryLanguage.SQL,
    "mysql": QueryLanguage.SQL,
    "bigquery": QueryLanguage.SQL,
    "sqlite": QueryLanguage.SQL,
    "oracle": QueryLanguage.SQL,
    "mssql": QueryLanguage.SQL,
    "clickhouse": QueryLanguage.SQL,
    "duckdb": QueryLanguage.SQL,
    # Time-series
    "influx": QueryLanguage.FLUX,
    # Document DB
    "mongo": QueryLanguage.MQL,
    "atlas": QueryLanguage.MQL,
    "documentdb": QueryLanguage.MQL,
    # Search
    "elastic": QueryLanguage.JSON,
}


def _resolve_query_language(driver: str) -> QueryLanguage:
    canonical = normalize_driver(driver)
    if canonical not in _DRIVER_TO_QUERY_LANGUAGE:
        raise ValueError(f"Unsupported driver for query validation: {driver!r}")
    return _DRIVER_TO_QUERY_LANGUAGE[canonical]


def _validator_to_validation_result(check: dict, language: QueryLanguage) -> ValidationResult:
    """Map the QueryValidator return shape into a ValidationResult."""
    is_safe = bool(check.get("is_safe"))
    return ValidationResult(
        valid=is_safe,
        error=None if is_safe else check.get("message"),
        dialect=language.value,
    )


class DatabaseQueryToolkit(AbstractToolkit):
    """Multi-database toolkit — discover schema, validate queries, execute."""

    tool_prefix: Optional[str] = "db"
    exclude_tools: tuple[str, ...] = ("get_source", "cleanup", "start", "stop")

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._source_cache: dict[str, AbstractDatabaseSource] = {}

    def get_source(self, driver: str) -> AbstractDatabaseSource:
        """Return a cached source instance for *driver* (not a tool)."""
        canonical = normalize_driver(driver)
        if canonical not in self._source_cache:
            cls = get_source_class(canonical)
            self._source_cache[canonical] = cls()
            self.logger.debug("Instantiated source for driver '%s'", canonical)
        return self._source_cache[canonical]

    async def cleanup(self) -> None:
        """Close cached source pools (not a tool — listed in exclude_tools)."""
        for source in self._source_cache.values():
            with contextlib.suppress(Exception):
                await source.close()
        self._source_cache.clear()

    # ── Public tools ────────────────────────────────────────────────

    async def get_database_metadata(
        self,
        driver: str,
        credentials: Optional[dict[str, Any]] = None,
        tables: Optional[list[str]] = None,
    ) -> dict:
        """Discover database schema. Call this FIRST before writing queries.

        Args:
            driver: canonical driver name (pg, mysql, mongo, ...).
            credentials: optional explicit credentials.
            tables: optional list of table/collection names to inspect.

        Returns:
            ``MetadataResult.model_dump()``.
        """
        source = self.get_source(driver)
        creds = await source.resolve_credentials(credentials)
        result = await source.get_metadata(creds, tables)
        return result.model_dump()

    async def validate_database_query(
        self,
        driver: str,
        query: str,
        credentials: Optional[dict[str, Any]] = None,
    ) -> dict:
        """Validate a query for safety AND syntax. Call BEFORE execute.

        Returns ``ValidationResult.model_dump()``. valid=False blocks
        DDL/DML (CREATE, DROP, INSERT, UPDATE, DELETE, EXEC, ...).
        """
        language = _resolve_query_language(driver)
        check = QueryValidator.validate_query(query, language)   # VERIFY signature
        if not check.get("is_safe", False):
            return _validator_to_validation_result(check, language).model_dump()
        # Second layer: source-level syntactic check (sqlglot for SQL drivers).
        source = self.get_source(driver)
        result = await source.validate_query(query)
        return result.model_dump()

    async def execute_database_query(
        self,
        driver: str,
        query: str,
        credentials: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> dict:
        """Execute a validated query and return all rows/documents.

        Re-runs the QueryValidator guard before contacting the source
        so a malicious caller cannot skip validate_database_query.
        """
        language = _resolve_query_language(driver)
        check = QueryValidator.validate_query(query, language)
        if not check.get("is_safe", False):
            return _validator_to_validation_result(check, language).model_dump()
        source = self.get_source(driver)
        creds = await source.resolve_credentials(credentials)
        result = await source.query(creds, query, params)
        return result.model_dump()

    async def fetch_database_row(
        self,
        driver: str,
        query: str,
        credentials: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> dict:
        """Execute a validated query expecting at most one row/document."""
        language = _resolve_query_language(driver)
        check = QueryValidator.validate_query(query, language)
        if not check.get("is_safe", False):
            return _validator_to_validation_result(check, language).model_dump()
        source = self.get_source(driver)
        creds = await source.resolve_credentials(credentials)
        result = await source.query_row(creds, query, params)
        return result.model_dump()
```

### Key Constraints

- BEFORE writing the validator wiring, run
  `grep -n "def validate_query\|def validate_sql_query\|def validate_flux_query" packages/ai-parrot/src/parrot/security/query_validator.py`
  to confirm the dispatcher's exact name and return shape.
  If `validate_query(query, language)` doesn't exist, dispatch in
  `_resolve_query_language` based on the language directly.
- The four public methods MUST have docstrings — `AbstractToolkit` uses
  them as the LLM-facing tool description.
- Method parameters must be JSON-serializable types (`str`, `dict`,
  `list`, primitives) — Pydantic schema generation requires it.
  Avoid pandas/asyncdb types in the signature.
- Do NOT reintroduce the `Args` schemas — they are generated
  automatically from the method signature by `_generate_args_schema_from_method`.

### References in Codebase

- Spec Sections 3 (Module 3 + 5), 6.
- `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py` — nearest
  existing `AbstractToolkit` subclass for reference on style and
  `exclude_tools` conventions.

---

## Acceptance Criteria

- [ ] `from parrot.tools.databasequery import DatabaseQueryToolkit` succeeds.
- [ ] `isinstance(DatabaseQueryToolkit(), AbstractToolkit)` is `True`.
- [ ] `len(DatabaseQueryToolkit().get_tools()) == 4`.
- [ ] Tool names are `db_get_database_metadata`, `db_validate_database_query`, `db_execute_database_query`, `db_fetch_database_row` (with `tool_prefix="db"`).
- [ ] `get_source` and `cleanup` do NOT appear in `get_tools()` output.
- [ ] `await DatabaseQueryToolkit().validate_database_query(driver="pg", query="DROP TABLE u")` returns `{"valid": False, "error": <DDL message>, "dialect": "sql"}`.
- [ ] `await DatabaseQueryToolkit().execute_database_query(driver="pg", query="DROP TABLE u")` returns the same `valid=False` payload WITHOUT calling `source.query` (verify with mock).
- [ ] No `AbstractTool` subclasses (`GetDatabaseMetadataTool`, etc.) remain in `toolkit.py`.

---

## Test Specification

Tests land in TASK-738. For this task, smoke-verify acceptance criteria
manually with `python -c` snippets.

---

## Agent Instructions

1. Confirm TASK-733 is complete (the new `databasequery/` package exists).
2. **Read** `parrot/security/query_validator.py` end-to-end to confirm the dispatcher signature and key names. Update the implementation pattern if it differs from the example above (the spec's pattern assumes `is_safe` keys based on `validate_sql_query`).
3. Implement the rewrite, then run the smoke imports / sanity checks.
4. Move file to `sdd/tasks/completed/`.

---

## Completion Note

## Completion Note

TASK-735 completed successfully.

- Rewrote toolkit.py: DatabaseToolkit → DatabaseQueryToolkit (inherits AbstractToolkit)
- Removed all 4 AbstractTool subclasses (GetDatabaseMetadataTool, ValidateDatabaseQueryTool, ExecuteDatabaseQueryTool, FetchDatabaseRowTool) and their Args schemas
- Added 4 public async methods with full Google docstrings
- Added _DRIVER_TO_QUERY_LANGUAGE mapping for 13 canonical drivers
- Wired QueryValidator.validate_query() guard in validate_database_query, execute_database_query, fetch_database_row
- tool_prefix='dq' per Q2 (avoids clash with SQLToolkit)
- exclude_tools=('get_source', 'cleanup', 'start', 'stop')
- Acceptance criteria verified: isinstance=True, 4 tools, names dq_*, DDL guard works
