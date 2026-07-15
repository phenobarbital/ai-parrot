---
type: Wiki Entity
title: SchedulerHandler
id: class:parrot.scheduler.manager.SchedulerHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: HTTP handler for schedule management.
---

# SchedulerHandler

Defined in [`parrot.scheduler.manager`](../summaries/mod:parrot.scheduler.manager.md).

```python
class SchedulerHandler(CorsViewMixin, web.View)
```

HTTP handler for schedule management.

## Methods

- `async def get(self)` — Get schedule(s).
- `async def post(self)` — Create new schedule.
- `async def delete(self)` — Delete schedule.
- `async def patch(self)` — Update schedule (enable/disable).
