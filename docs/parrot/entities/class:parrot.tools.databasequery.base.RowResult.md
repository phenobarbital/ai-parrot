---
type: Wiki Entity
title: RowResult
id: class:parrot.tools.databasequery.base.RowResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Result of a single-row fetch operation.
---

# RowResult

Defined in [`parrot.tools.databasequery.base`](../summaries/mod:parrot.tools.databasequery.base.md).

```python
class RowResult(BaseModel)
```

Result of a single-row fetch operation.

Attributes:
    driver: The database driver used.
    row: The fetched row as a dictionary, or None if not found.
    found: Whether a row was found.
    execution_time_ms: Query execution time in milliseconds.
