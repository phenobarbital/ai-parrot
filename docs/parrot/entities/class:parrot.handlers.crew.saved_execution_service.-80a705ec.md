---
type: Wiki Entity
title: ReplayValidationError
id: class:parrot.handlers.crew.saved_execution_service.ReplayValidationError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: The replay/schedule request fails validation for reasons other than
relates_to:
- concept: class:parrot.handlers.crew.saved_execution_service.SavedExecutionError
  rel: extends
---

# ReplayValidationError

Defined in [`parrot.handlers.crew.saved_execution_service`](../summaries/mod:parrot.handlers.crew.saved_execution_service.md).

```python
class ReplayValidationError(SavedExecutionError)
```

The replay/schedule request fails validation for reasons other than
"not found" (missing prompt, unsupported method, unknown method).
