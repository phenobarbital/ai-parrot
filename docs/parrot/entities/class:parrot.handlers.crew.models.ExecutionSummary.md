---
type: Wiki Entity
title: ExecutionSummary
id: class:parrot.handlers.crew.models.ExecutionSummary
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Summary of a saved execution for list responses.
---

# ExecutionSummary

Defined in [`parrot.handlers.crew.models`](../summaries/mod:parrot.handlers.crew.models.md).

```python
class ExecutionSummary(BaseModel)
```

Summary of a saved execution for list responses.

Attributes:
    id: Unique identifier of the saved execution record.
    crew_name: Name of the crew that produced this execution.
    method: Execution method used (e.g. ``"run_sequential"``).
    prompt: Original prompt/query, if captured.
    user_id: Identifier of the user who triggered the execution.
    tenant: Tenant the execution belongs to. Defaults to ``"global"``.
    timestamp: When the execution was persisted.
    status: Execution status. Defaults to ``"success"``.
