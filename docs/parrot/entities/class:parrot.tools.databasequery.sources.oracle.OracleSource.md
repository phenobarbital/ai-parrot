---
type: Wiki Entity
title: OracleSource
id: class:parrot.tools.databasequery.sources.oracle.OracleSource
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Oracle Database source.
relates_to:
- concept: class:parrot.tools.databasequery.base.AbstractDatabaseSource
  rel: extends
---

# OracleSource

Defined in [`parrot.tools.databasequery.sources.oracle`](../summaries/mod:parrot.tools.databasequery.sources.oracle.md).

```python
class OracleSource(AbstractDatabaseSource)
```

Oracle Database source.

Uses the asyncdb ``oracle`` driver. Validates queries with the
``oracle`` sqlglot dialect. Discovers schema via ALL_TAB_COLUMNS.

## Methods

- `async def get_default_credentials(self) -> dict[str, Any]` — Return default Oracle credentials from environment variables.
- `async def get_metadata(self, credentials: dict[str, Any], tables: list[str] | None=None) -> MetadataResult` — Discover Oracle schema via ALL_TAB_COLUMNS.
- `async def query(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> QueryResult` — Execute an Oracle SQL query and return all results.
- `async def query_row(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> RowResult` — Execute an Oracle SQL query and return the first row.
