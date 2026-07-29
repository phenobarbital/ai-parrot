---
type: Wiki Entity
title: SchedulerJobsHandler
id: class:parrot.handlers.scheduler.SchedulerJobsHandler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: CRUD handler for scheduler jobs persisted in APScheduler and Postgres.
---

# SchedulerJobsHandler

Defined in [`parrot.handlers.scheduler`](../summaries/mod:parrot.handlers.scheduler.md).

```python
class SchedulerJobsHandler(BaseView)
```

CRUD handler for scheduler jobs persisted in APScheduler and Postgres.

## Methods

- `def post_init(self, *args, **kwargs)`
- `def manager(self)`
- `async def get(self) -> web.Response`
- `async def post(self) -> web.Response`
- `async def patch(self) -> web.Response`
- `async def delete(self) -> web.Response`
