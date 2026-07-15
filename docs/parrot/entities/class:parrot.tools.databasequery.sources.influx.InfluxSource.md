---
type: Wiki Entity
title: InfluxSource
id: class:parrot.tools.databasequery.sources.influx.InfluxSource
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: InfluxDB time-series database source.
relates_to:
- concept: class:parrot.tools.databasequery.base.AbstractDatabaseSource
  rel: extends
---

# InfluxSource

Defined in [`parrot.tools.databasequery.sources.influx`](../summaries/mod:parrot.tools.databasequery.sources.influx.md).

```python
class InfluxSource(AbstractDatabaseSource)
```

InfluxDB time-series database source.

Uses Flux query language (InfluxDB v2+). Validates queries by checking
for the required ``from(bucket:...)`` clause. Discovers schema by
listing buckets and field keys.

## Methods

- `async def get_default_credentials(self) -> dict[str, Any]` — Return default InfluxDB credentials from environment variables.
- `async def test_connection(self, credentials: dict[str, Any]) -> bool` — Test InfluxDB connectivity using the ``buckets()`` Flux query.
- `async def validate_query(self, query: str) -> ValidationResult` — Validate a Flux query string.
- `async def get_metadata(self, credentials: dict[str, Any], tables: list[str] | None=None) -> MetadataResult` — Discover InfluxDB schema: buckets as tables, field keys as columns.
- `async def query(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> QueryResult` — Execute a Flux query and return all results.
- `async def query_row(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> RowResult` — Execute a Flux query and return the first record.
