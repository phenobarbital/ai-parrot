---
type: Wiki Entity
title: QueryResult
id: class:parrot.tools.databasequery.base.QueryResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Result of a multi-row query execution.
---

# QueryResult

Defined in [`parrot.tools.databasequery.base`](../summaries/mod:parrot.tools.databasequery.base.md).

```python
class QueryResult(BaseModel)
```

Result of a multi-row query execution.

Attributes:
    driver: The database driver used.
    rows: List of rows as dictionaries.
    row_count: Number of rows returned.
    columns: List of column names.
    execution_time_ms: Query execution time in milliseconds.
