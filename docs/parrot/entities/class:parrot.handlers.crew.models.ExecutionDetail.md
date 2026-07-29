---
type: Wiki Entity
title: ExecutionDetail
id: class:parrot.handlers.crew.models.ExecutionDetail
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Full execution record with payload, extending :class:`ExecutionSummary`.
relates_to:
- concept: class:parrot.handlers.crew.models.ExecutionSummary
  rel: extends
---

# ExecutionDetail

Defined in [`parrot.handlers.crew.models`](../summaries/mod:parrot.handlers.crew.models.md).

```python
class ExecutionDetail(ExecutionSummary)
```

Full execution record with payload, extending :class:`ExecutionSummary`.

Attributes:
    session_id: Session identifier associated with the execution.
    payload: Full execution result payload.
