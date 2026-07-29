---
type: Wiki Entity
title: ClickHouseSource
id: class:parrot.tools.databasequery.sources.clickhouse.ClickHouseSource
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: ClickHouse OLAP database source.
relates_to:
- concept: class:parrot.tools.databasequery.base.AbstractDatabaseSource
  rel: extends
---

# ClickHouseSource

Defined in [`parrot.tools.databasequery.sources.clickhouse`](../summaries/mod:parrot.tools.databasequery.sources.clickhouse.md).

```python
class ClickHouseSource(AbstractDatabaseSource)
```

ClickHouse OLAP database source.

Uses the asyncdb ``clickhouse`` driver. Validates queries with the
``clickhouse`` sqlglot dialect. Discovers schema via system.columns.

## Methods

- `async def get_default_credentials(self) -> dict[str, Any]` — Return default ClickHouse credentials from environment variables.
- `async def get_metadata(self, credentials: dict[str, Any], tables: list[str] | None=None) -> MetadataResult` — Discover ClickHouse schema via system.columns.
- `async def query(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> QueryResult` — Execute a ClickHouse SQL query and return all results.
- `async def query_row(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> RowResult` — Execute a ClickHouse SQL query and return the first row.
