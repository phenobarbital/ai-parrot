---
type: Wiki Entity
title: BaseSchedulerCallback
id: class:parrot.scheduler.functions.BaseSchedulerCallback
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Base class for scheduler callbacks executed after successful jobs.
relates_to:
- concept: class:parrot.notifications.NotificationMixin
  rel: extends
---

# BaseSchedulerCallback

Defined in [`parrot.scheduler.functions`](../summaries/mod:parrot.scheduler.functions.md).

```python
class BaseSchedulerCallback(NotificationMixin)
```

Base class for scheduler callbacks executed after successful jobs.

## Methods

- `def describe(cls) -> Dict[str, Any]`
- `def process_output(self, result: Any) -> Dict[str, Any]` — Normalize an AIMessage-like response into text, markdown and data.
- `async def run(self, result: Any, *, schedule_id: str, agent_name: str, **kwargs) -> Dict[str, Any]`
