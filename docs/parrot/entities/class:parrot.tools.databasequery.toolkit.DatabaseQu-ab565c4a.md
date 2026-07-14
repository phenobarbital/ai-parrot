---
type: Wiki Entity
title: DatabaseQueryToolkit
id: class:parrot.tools.databasequery.toolkit.DatabaseQueryToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Multi-database toolkit — discover schema, validate queries, execute.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# DatabaseQueryToolkit

Defined in [`parrot.tools.databasequery.toolkit`](../summaries/mod:parrot.tools.databasequery.toolkit.md).

```python
class DatabaseQueryToolkit(AbstractToolkit)
```

Multi-database toolkit — discover schema, validate queries, execute.

Inherits from ``AbstractToolkit`` so public async methods are
automatically discovered and wrapped as ``AbstractTool`` instances.  Use
``get_tools()`` to retrieve them and attach them to an Agent or AgentCrew.

Tool names (with ``tool_prefix="dq"``):
  - ``dq_get_database_metadata``
  - ``dq_validate_query``
  - ``dq_execute_database_query``
  - ``dq_fetch_database_row``
  - ``dq_get_table_metadata``
  - ``dq_test_connection``
  - ``dq_save_result`` (only when ``output_dir`` is configured)

DDL/DML guard:
    Every query-executing method calls
    ``parrot.security.QueryValidator.validate_query`` BEFORE contacting the
    underlying source, ensuring that dangerous statements (``DROP``,
    ``INSERT``, ``UPDATE``, …) are rejected even if the caller skips
    ``validate_query``.

Supported drivers (canonical names):
    ``pg``, ``mysql``, ``bigquery``, ``sqlite``, ``oracle``, ``mssql``,
    ``clickhouse``, ``duckdb``, ``influx``, ``mongo``, ``atlas``,
    ``documentdb``, ``elastic`` — plus all aliases resolved by
    ``normalize_driver()``.

## Methods

- `def get_source(self, driver: str) -> AbstractDatabaseSource` — Return a (cached) source instance for *driver*.
- `async def cleanup(self) -> None` — Close all cached source pools.
- `async def get_database_metadata(self, driver: str, credentials: Optional[dict[str, Any]]=None, tables: Optional[list[str]]=None) -> MetadataResult` — Discover database schema. Call this FIRST before writing queries.
- `async def validate_query(self, driver: str, query: str) -> ValidationResult` — Validate a query for safety and syntax. Call BEFORE executing.
- `async def get_table_metadata(self, driver: str, table: str, credentials: Optional[dict[str, Any]]=None) -> MetadataResult` — Get detailed metadata for a specific table or collection.
- `async def test_connection(self, driver: str, credentials: Optional[dict[str, Any]]=None) -> dict[str, Any]` — Test connectivity to the target database.
- `async def execute_database_query(self, driver: str, query: str, credentials: Optional[dict[str, Any]]=None, params: Optional[dict[str, Any]]=None, max_rows: int=10000) -> Union[QueryResult, ValidationResult]` — Execute a validated query and return all matching rows or documents.
- `async def fetch_database_row(self, driver: str, query: str, credentials: Optional[dict[str, Any]]=None, params: Optional[dict[str, Any]]=None, max_rows: int=1) -> Union[RowResult, ValidationResult]` — Execute a query and return at most one matching row or document.
- `async def save_result(self, result: dict[str, Any], filename: Optional[str]=None, file_format: str='csv') -> dict[str, Any]` — Save a prior query result to a file on disk.
