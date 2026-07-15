---
type: Wiki Entity
title: ExecutionFilter
id: class:parrot.handlers.crew.models.ExecutionFilter
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Filters for listing saved executions.
---

# ExecutionFilter

Defined in [`parrot.handlers.crew.models`](../summaries/mod:parrot.handlers.crew.models.md).

```python
class ExecutionFilter(BaseModel)
```

Filters for listing saved executions.

Attributes:
    crew_name: Restrict results to a single crew name.
    method: Restrict results to a single execution method (e.g. ``"run_flow"``).
    date_from: Only include executions at or after this timestamp.
    date_to: Only include executions at or before this timestamp.
