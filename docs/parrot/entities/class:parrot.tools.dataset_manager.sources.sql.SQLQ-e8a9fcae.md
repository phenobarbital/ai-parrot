---
type: Wiki Entity
title: SQLQuerySource
id: class:parrot.tools.dataset_manager.sources.sql.SQLQuerySource
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: DataSource backed by a user-provided SQL template with {param} interpolation.
relates_to:
- concept: class:parrot.tools.dataset_manager.sources.base.DataSource
  rel: extends
---

# SQLQuerySource

Defined in [`parrot.tools.dataset_manager.sources.sql`](../summaries/mod:parrot.tools.dataset_manager.sources.sql.md).

```python
class SQLQuerySource(DataSource)
```

DataSource backed by a user-provided SQL template with {param} interpolation.

SQL can contain placeholders like ``{start_date}``, ``{ticker}`` etc.
All placeholders are validated and escaped at ``fetch()`` time before execution.

Args:
    sql: SQL template string with optional ``{param}`` placeholders.
    driver: AsyncDB driver name (``pg``, ``mysql``, ``bigquery``, etc.).
    dsn: Optional DSN string. For PostgreSQL drivers, resolved via
        ``get_default_credentials(driver)`` when ``None``.
    credentials: Optional credentials dict for the database connection.
        Used when ``dsn`` is not set (e.g. BigQuery needs a credentials
        path + project_id, not a DSN). When both ``dsn`` and
        ``credentials`` are ``None``, defaults are resolved from
        navconfig for the driver (mirrors ``TableSource`` behavior).
    cache_ttl: Cache TTL in seconds. Defaults to 3600.

## Methods

- `def cache_key(self) -> str` — Stable Redis cache key for this source.
- `def describe(self) -> str` — Human-readable description for the LLM.
- `async def prefetch_schema(self) -> Dict[str, str]` — Return empty dict — schema only available after first fetch.
- `async def fetch(self, **params) -> pd.DataFrame` — Execute the SQL template and return a DataFrame.
