---
type: Wiki Entity
title: WorkerType
id: class:parrot_tools.interfaces.workday.handlers.workers.WorkerType
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Handler for the Workday Get_Workers operation, batching pages
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# WorkerType

Defined in [`parrot_tools.interfaces.workday.handlers.workers`](../summaries/mod:parrot_tools.interfaces.workday.handlers.workers.md).

```python
class WorkerType(WorkdayTypeBase)
```

Handler for the Workday Get_Workers operation, batching pages
so that no more than `max_parallel` requests run concurrently.

## Methods

- `async def execute(self, **kwargs) -> pd.DataFrame` — Execute the Get_Workers operation and return a pandas DataFrame.
