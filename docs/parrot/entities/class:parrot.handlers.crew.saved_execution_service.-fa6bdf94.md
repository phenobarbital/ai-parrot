---
type: Wiki Entity
title: SavedExecutionError
id: class:parrot.handlers.crew.saved_execution_service.SavedExecutionError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Base exception for SavedExecutionService errors.
---

# SavedExecutionError

Defined in [`parrot.handlers.crew.saved_execution_service`](../summaries/mod:parrot.handlers.crew.saved_execution_service.md).

```python
class SavedExecutionError(ValueError)
```

Base exception for SavedExecutionService errors.

Subclasses ``ValueError`` for backward compatibility with existing
``except ValueError`` callers/tests, while giving the HTTP handler a
typed hierarchy to map to status codes instead of fragile substring
matching on the exception message.
