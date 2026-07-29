---
type: Wiki Entity
title: ExecutionNotFoundError
id: class:parrot.handlers.crew.saved_execution_service.ExecutionNotFoundError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: The requested execution record doesn't exist (or isn't owned by the
relates_to:
- concept: class:parrot.handlers.crew.saved_execution_service.SavedExecutionError
  rel: extends
---

# ExecutionNotFoundError

Defined in [`parrot.handlers.crew.saved_execution_service`](../summaries/mod:parrot.handlers.crew.saved_execution_service.md).

```python
class ExecutionNotFoundError(SavedExecutionError)
```

The requested execution record doesn't exist (or isn't owned by the
caller — ownership failures are indistinguishable from "not found" by
design, to avoid leaking the existence of other tenants'/users' records).
