---
type: Wiki Entity
title: RetryContext
id: class:parrot.bots.database.retries.RetryContext
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Payload returned by SQLToolkit.execute_query on a retryable error.
---

# RetryContext

Defined in [`parrot.bots.database.retries`](../summaries/mod:parrot.bots.database.retries.md).

```python
class RetryContext(BaseModel)
```

Payload returned by SQLToolkit.execute_query on a retryable error.

Signals to DatabaseAgent.ask() that the last query failed but is worth
retrying.  The LLM receives this context on the re-ask so it can generate
a corrected query.
