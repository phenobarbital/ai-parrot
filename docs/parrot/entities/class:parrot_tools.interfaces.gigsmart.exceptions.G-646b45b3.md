---
type: Wiki Entity
title: GigSmartConflictError
id: class:parrot_tools.interfaces.gigsmart.exceptions.GigSmartConflictError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Conflict with the current resource state.
relates_to:
- concept: class:parrot_tools.interfaces.gigsmart.exceptions.GigSmartError
  rel: extends
---

# GigSmartConflictError

Defined in [`parrot_tools.interfaces.gigsmart.exceptions`](../summaries/mod:parrot_tools.interfaces.gigsmart.exceptions.md).

```python
class GigSmartConflictError(GigSmartError)
```

Conflict with the current resource state.

Raised when the API returns a ``CONFLICT`` extension code — for example,
attempting to hire a worker for an already-filled shift.
