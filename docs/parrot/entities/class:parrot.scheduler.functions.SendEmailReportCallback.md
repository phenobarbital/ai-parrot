---
type: Wiki Entity
title: SendEmailReportCallback
id: class:parrot.scheduler.functions.SendEmailReportCallback
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Class SendEmailReportCallback in parrot.scheduler.functions
relates_to:
- concept: class:parrot.scheduler.functions.BaseSchedulerCallback
  rel: extends
---

# SendEmailReportCallback

Defined in [`parrot.scheduler.functions`](../summaries/mod:parrot.scheduler.functions.md).

```python
class SendEmailReportCallback(BaseSchedulerCallback)
```

## Methods

- `async def run(self, result: Any, *, schedule_id: str, agent_name: str, **kwargs) -> Dict[str, Any]`
