---
type: Wiki Entity
title: BigQuerySource
id: class:parrot.tools.databasequery.sources.bigquery.BigQuerySource
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Google BigQuery database source.
relates_to:
- concept: class:parrot.tools.databasequery.base.AbstractDatabaseSource
  rel: extends
---

# BigQuerySource

Defined in [`parrot.tools.databasequery.sources.bigquery`](../summaries/mod:parrot.tools.databasequery.sources.bigquery.md).

```python
class BigQuerySource(AbstractDatabaseSource)
```

Google BigQuery database source.

Uses the asyncdb ``bigquery`` driver. Validates queries with the
``bigquery`` sqlglot dialect. Discovers schema via INFORMATION_SCHEMA.

## Methods

- `async def get_default_credentials(self) -> dict[str, Any]` — Return default BigQuery credentials from environment variables.
- `async def get_metadata(self, credentials: dict[str, Any], tables: list[str] | None=None) -> MetadataResult` — Discover BigQuery schema via INFORMATION_SCHEMA.COLUMNS.
- `async def query(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> QueryResult` — Execute a BigQuery SQL query and return all results.
- `async def query_row(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> RowResult` — Execute a BigQuery SQL query and return the first row.
