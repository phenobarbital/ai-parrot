---
type: Wiki Entity
title: CrewNotFoundError
id: class:parrot.handlers.crew.saved_execution_service.CrewNotFoundError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: The crew referenced by a saved execution no longer exists (or no
relates_to:
- concept: class:parrot.handlers.crew.saved_execution_service.SavedExecutionError
  rel: extends
---

# CrewNotFoundError

Defined in [`parrot.handlers.crew.saved_execution_service`](../summaries/mod:parrot.handlers.crew.saved_execution_service.md).

```python
class CrewNotFoundError(SavedExecutionError)
```

The crew referenced by a saved execution no longer exists (or no
``bot_manager`` is configured to resolve it).
