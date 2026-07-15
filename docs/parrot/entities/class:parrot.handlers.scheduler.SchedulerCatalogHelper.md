---
type: Wiki Entity
title: SchedulerCatalogHelper
id: class:parrot.handlers.scheduler.SchedulerCatalogHelper
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Helper for scheduler metadata exposed through REST endpoints.
---

# SchedulerCatalogHelper

Defined in [`parrot.handlers.scheduler`](../summaries/mod:parrot.handlers.scheduler.md).

```python
class SchedulerCatalogHelper(BaseHandler)
```

Helper for scheduler metadata exposed through REST endpoints.

## Methods

- `def list_schedule_types() -> list[str]`
- `def list_scheduler_types(app: web.Application) -> list[str]`
- `def list_callbacks() -> list[dict[str, Any]]`
