---
type: Wiki Entity
title: SendNotifyReportCallback
id: class:parrot.scheduler.functions.SendNotifyReportCallback
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Class SendNotifyReportCallback in parrot.scheduler.functions
relates_to:
- concept: class:parrot.scheduler.functions.BaseSchedulerCallback
  rel: extends
---

# SendNotifyReportCallback

Defined in [`parrot.scheduler.functions`](../summaries/mod:parrot.scheduler.functions.md).

```python
class SendNotifyReportCallback(BaseSchedulerCallback)
```

## Methods

- `async def run(self, result: Any, *, schedule_id: str, agent_name: str, **kwargs) -> Dict[str, Any]`
