---
type: Wiki Entity
title: MSSQLSource
id: class:parrot.tools.databasequery.sources.mssql.MSSQLSource
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Microsoft SQL Server database source with stored procedure support.
relates_to:
- concept: class:parrot.tools.databasequery.base.AbstractDatabaseSource
  rel: extends
---

# MSSQLSource

Defined in [`parrot.tools.databasequery.sources.mssql`](../summaries/mod:parrot.tools.databasequery.sources.mssql.md).

```python
class MSSQLSource(AbstractDatabaseSource)
```

Microsoft SQL Server database source with stored procedure support.

Uses the asyncdb ``mssql`` driver. Validates queries with the ``tsql``
sqlglot dialect, with special handling for EXEC/EXECUTE stored procedure calls.
Exposes stored procedures alongside tables in metadata discovery.

## Methods

- `async def get_default_credentials(self) -> dict[str, Any]` — Return default MSSQL credentials from environment variables.
- `async def validate_query(self, query: str) -> ValidationResult` — Validate a T-SQL query, including EXEC/EXECUTE statements.
- `async def get_metadata(self, credentials: dict[str, Any], tables: list[str] | None=None) -> MetadataResult` — Discover MSSQL schema, including tables and stored procedures.
- `async def query(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> QueryResult` — Execute a T-SQL query or stored procedure call.
- `async def query_row(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> RowResult` — Execute a T-SQL query and return the first row.
