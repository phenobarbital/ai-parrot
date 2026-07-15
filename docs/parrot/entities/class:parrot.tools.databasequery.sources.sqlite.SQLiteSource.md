---
type: Wiki Entity
title: SQLiteSource
id: class:parrot.tools.databasequery.sources.sqlite.SQLiteSource
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: SQLite database source.
relates_to:
- concept: class:parrot.tools.databasequery.base.AbstractDatabaseSource
  rel: extends
---

# SQLiteSource

Defined in [`parrot.tools.databasequery.sources.sqlite`](../summaries/mod:parrot.tools.databasequery.sources.sqlite.md).

```python
class SQLiteSource(AbstractDatabaseSource)
```

SQLite database source.

Uses the asyncdb ``sqlite`` driver. Validates queries with the
``sqlite`` sqlglot dialect. Discovers schema via PRAGMA and sqlite_master.

## Methods

- `async def get_default_credentials(self) -> dict[str, Any]` — Return default SQLite credentials from environment variables.
- `async def get_metadata(self, credentials: dict[str, Any], tables: list[str] | None=None) -> MetadataResult` — Discover SQLite schema via PRAGMA table_info() and sqlite_master.
- `async def query(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> QueryResult` — Execute a SQL query and return all results.
- `async def query_row(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> RowResult` — Execute a SQL query and return the first row.
