---
type: Wiki Entity
title: CreateFileCallback
id: class:parrot.scheduler.functions.CreateFileCallback
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Class CreateFileCallback in parrot.scheduler.functions
relates_to:
- concept: class:parrot.scheduler.functions.BaseSchedulerCallback
  rel: extends
---

# CreateFileCallback

Defined in [`parrot.scheduler.functions`](../summaries/mod:parrot.scheduler.functions.md).

```python
class CreateFileCallback(BaseSchedulerCallback)
```

## Methods

- `async def run(self, result: Any, *, schedule_id: str, agent_name: str, **kwargs) -> Dict[str, Any]`
