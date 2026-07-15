---
type: Wiki Entity
title: ScheduleRequest
id: class:parrot.handlers.crew.models.ScheduleRequest
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Request body for scheduling a saved execution.
---

# ScheduleRequest

Defined in [`parrot.handlers.crew.models`](../summaries/mod:parrot.handlers.crew.models.md).

```python
class ScheduleRequest(BaseModel)
```

Request body for scheduling a saved execution.

Attributes:
    schedule_type: One of ONCE, DAILY, WEEKLY, MONTHLY, INTERVAL, CRON, CRONTAB.
    schedule_config: Schedule configuration payload for the given type.
    created_by: Identifier of the user creating the schedule.
    created_email: Email of the user creating the schedule.
    metadata: Additional metadata to store with the schedule.
    callbacks: Optional list of callback configurations.
