---
type: Wiki Entity
title: DuckDBSource
id: class:parrot.tools.databasequery.sources.duckdb.DuckDBSource
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: DuckDB embedded analytical database source.
relates_to:
- concept: class:parrot.tools.databasequery.base.AbstractDatabaseSource
  rel: extends
---

# DuckDBSource

Defined in [`parrot.tools.databasequery.sources.duckdb`](../summaries/mod:parrot.tools.databasequery.sources.duckdb.md).

```python
class DuckDBSource(AbstractDatabaseSource)
```

DuckDB embedded analytical database source.

Uses the asyncdb ``duckdb`` driver. Validates queries with the
``duckdb`` sqlglot dialect. Supports file-based and in-memory operation.
Discovers schema via information_schema.columns.

## Methods

- `async def get_default_credentials(self) -> dict[str, Any]` — Return default DuckDB credentials.
- `async def get_metadata(self, credentials: dict[str, Any], tables: list[str] | None=None) -> MetadataResult` — Discover DuckDB schema via information_schema.columns.
- `async def query(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> QueryResult` — Execute a DuckDB SQL query and return all results.
- `async def query_row(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> RowResult` — Execute a DuckDB SQL query and return the first row.
