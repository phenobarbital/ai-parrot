---
type: Wiki Entity
title: PostgresSource
id: class:parrot.tools.databasequery.sources.postgres.PostgresSource
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: PostgreSQL database source.
relates_to:
- concept: class:parrot.tools.databasequery.base.AbstractDatabaseSource
  rel: extends
---

# PostgresSource

Defined in [`parrot.tools.databasequery.sources.postgres`](../summaries/mod:parrot.tools.databasequery.sources.postgres.md).

```python
class PostgresSource(AbstractDatabaseSource)
```

PostgreSQL database source.

Uses the asyncdb ``pg`` driver. Validates queries with the
``postgres`` sqlglot dialect. Discovers schema via ``information_schema``.

## Methods

- `async def get_default_credentials(self) -> dict[str, Any]` — Return default PostgreSQL credentials from environment variables.
- `async def get_metadata(self, credentials: dict[str, Any], tables: list[str] | None=None) -> MetadataResult` — Discover PostgreSQL schema via information_schema.
- `async def query(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> QueryResult` — Execute a SQL query and return all results.
- `async def query_row(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> RowResult` — Execute a SQL query and return the first row.
