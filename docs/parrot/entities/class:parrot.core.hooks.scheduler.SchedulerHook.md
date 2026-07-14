---
type: Wiki Entity
title: SchedulerHook
id: class:parrot.core.hooks.scheduler.SchedulerHook
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Periodically fires events using APScheduler (cron or interval).
relates_to:
- concept: class:parrot.core.hooks.base.BaseHook
  rel: extends
---

# SchedulerHook

Defined in [`parrot.core.hooks.scheduler`](../summaries/mod:parrot.core.hooks.scheduler.md).

```python
class SchedulerHook(BaseHook)
```

Periodically fires events using APScheduler (cron or interval).

## Methods

- `async def start(self) -> None`
- `async def stop(self) -> None`
