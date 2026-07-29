---
type: Concept
title: add_row_limit()
id: func:parrot.tools.databasequery.base.add_row_limit
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Inject a dialect-specific row limit into a query string.
---

# add_row_limit

```python
def add_row_limit(query: str, max_rows: int, driver: str) -> str
```

Inject a dialect-specific row limit into a query string.

Ported from ``DatabaseQueryTool._add_row_limit()`` (tool.py:692-739) as a
shared free function so both the toolkit and the legacy tool can reuse it.

Supported query languages:

- **SQL** (pg, mysql, sqlite, clickhouse, duckdb, bigquery):
  Appends ``LIMIT N`` unless a ``LIMIT`` clause is already present.
- **SQL (no bare LIMIT)** (oracle, mssql, sqlserver): Returns query
  unchanged. These dialects require ``SELECT TOP N`` (T-SQL) or
  ``FETCH FIRST N ROWS ONLY`` (Oracle 12c+) which cannot be injected
  safely without full query parsing. Callers must embed the limit
  in the query string itself.
- **Flux** (influx): Appends ``|> limit(n: N)`` unless already present.
- **JSON/Elasticsearch** (elastic): Sets ``"size": N`` in the JSON body
  unless ``"size"`` already exists with a smaller-or-equal value.
- **MQL/MongoDB** (mongo, atlas, documentdb): Returns the query unchanged
  (MongoDB limits are passed as a parameter to the connection, not in the
  query string).

Args:
    query: The original query string.
    max_rows: Maximum number of rows/documents to return. If ``0`` or
        negative, the query is returned unchanged.
    driver: Canonical driver name or alias (e.g. ``'pg'``, ``'postgres'``,
        ``'influx'``, ``'elastic'``, ``'mongo'``).

Returns:
    The modified query string with a row limit injected, or the original
    query if already limited or the driver does not support string-level
    limit injection.

Examples:
    >>> add_row_limit("SELECT * FROM t", 100, "pg")
    'SELECT * FROM t LIMIT 100'
    >>> add_row_limit("SELECT * FROM t LIMIT 50", 100, "pg")
    'SELECT * FROM t LIMIT 50'
    >>> add_row_limit('from(bucket:"b") |> range(start:-1h)', 10, "influx")
    'from(bucket:"b") |> range(start:-1h) |> limit(n: 10)'
    >>> add_row_limit('{"status":"active"}', 10, "mongo")
    '{"status":"active"}'
