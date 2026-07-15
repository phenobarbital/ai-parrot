---
type: Wiki Entity
title: SaveDataCallback
id: class:parrot.scheduler.functions.SaveDataCallback
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Class SaveDataCallback in parrot.scheduler.functions
relates_to:
- concept: class:parrot.scheduler.functions.BaseSchedulerCallback
  rel: extends
---

# SaveDataCallback

Defined in [`parrot.scheduler.functions`](../summaries/mod:parrot.scheduler.functions.md).

```python
class SaveDataCallback(BaseSchedulerCallback)
```

## Methods

- `async def run(self, result: Any, *, schedule_id: str, agent_name: str, **kwargs) -> Dict[str, Any]`
