---
type: Wiki Entity
title: SQLDataSource
id: class:parrot_loaders.extractors.sql_source.SQLDataSource
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extract structured records from SQL queries.
relates_to:
- concept: class:parrot_loaders.extractors.base.ExtractDataSource
  rel: extends
---

# SQLDataSource

Defined in [`parrot_loaders.extractors.sql_source`](../summaries/mod:parrot_loaders.extractors.sql_source.md).

```python
class SQLDataSource(ExtractDataSource)
```

Extract structured records from SQL queries.

Config:
    dsn: str — Database connection string.
    query: str — SQL SELECT query to execute.
    params: dict — Query parameters (for parameterized queries).

Uses asyncpg for PostgreSQL. The query MUST be read-only (SELECT only).

Args:
    name: Human-readable name for logging and reporting.
    config: Source-specific configuration.

## Methods

- `async def extract(self, fields: list[str] | None=None, filters: dict[str, Any] | None=None) -> ExtractionResult` — Execute SQL query and return rows as records.
- `async def list_fields(self) -> list[str]` — Execute query with LIMIT 0 to get column names.
