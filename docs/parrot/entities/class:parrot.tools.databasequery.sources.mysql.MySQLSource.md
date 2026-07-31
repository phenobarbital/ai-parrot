---
type: Wiki Entity
title: MySQLSource
id: class:parrot.tools.databasequery.sources.mysql.MySQLSource
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: MySQL/MariaDB database source.
relates_to:
- concept: class:parrot.tools.databasequery.base.AbstractDatabaseSource
  rel: extends
---

# MySQLSource

Defined in [`parrot.tools.databasequery.sources.mysql`](../summaries/mod:parrot.tools.databasequery.sources.mysql.md).

```python
class MySQLSource(AbstractDatabaseSource)
```

MySQL/MariaDB database source.

Uses the asyncdb ``mysql`` driver. Validates queries with the
``mysql`` sqlglot dialect. Discovers schema via ``information_schema``.

## Methods

- `async def get_default_credentials(self) -> dict[str, Any]` — Return default MySQL credentials from environment variables.
- `async def get_metadata(self, credentials: dict[str, Any], tables: list[str] | None=None) -> MetadataResult` — Discover MySQL schema via information_schema.
- `async def query(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> QueryResult` — Execute a SQL query and return all results.
- `async def query_row(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> RowResult` — Execute a SQL query and return the first row.
