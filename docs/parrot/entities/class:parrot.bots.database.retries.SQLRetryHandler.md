---
type: Wiki Entity
title: SQLRetryHandler
id: class:parrot.bots.database.retries.SQLRetryHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: SQL-specific retry handler with error learning.
relates_to:
- concept: class:parrot.bots.database.retries.RetryHandler
  rel: extends
---

# SQLRetryHandler

Defined in [`parrot.bots.database.retries`](../summaries/mod:parrot.bots.database.retries.md).

```python
class SQLRetryHandler(RetryHandler)
```

SQL-specific retry handler with error learning.

## Methods

- `async def retry_query(self, query: str, error: Exception, attempt: int) -> Optional[str]` — Attempt to produce a corrected SQL query.
