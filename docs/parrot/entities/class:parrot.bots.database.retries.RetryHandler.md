---
type: Wiki Entity
title: RetryHandler
id: class:parrot.bots.database.retries.RetryHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Base retry handler for any database toolkit.
---

# RetryHandler

Defined in [`parrot.bots.database.retries`](../summaries/mod:parrot.bots.database.retries.md).

```python
class RetryHandler
```

Base retry handler for any database toolkit.

Subclass and override ``_is_retryable_error`` and ``retry_query``
for database-specific error patterns.

## Methods

- `async def retry_query(self, query: str, error: Exception, attempt: int) -> Optional[str]` — Attempt to produce a corrected query after an error.
