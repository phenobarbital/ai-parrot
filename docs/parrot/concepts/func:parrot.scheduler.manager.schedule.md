---
type: Concept
title: schedule()
id: func:parrot.scheduler.manager.schedule
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Decorator to mark agent methods for scheduling.
---

# schedule

```python
def schedule(schedule_type: ScheduleType=ScheduleType.DAILY, *, success_callback: Optional[Callable]=None, send_result: Optional[Dict[str, Any]]=None, callbacks: Optional[List[Dict[str, Any]]]=None, **schedule_config)
```

Decorator to mark agent methods for scheduling.

Usage:
    @schedule(schedule_type=ScheduleType.DAILY, hour=9, minute=0)
    async def generate_daily_report(self):
        ...

    @schedule(schedule_type=ScheduleType.INTERVAL, hours=2)
    async def check_updates(self):
        ...

    @schedule(
        schedule_type=ScheduleType.INTERVAL,
        minutes=30,
        success_callback=my_callback,
    )
    async def poll(self):
        ...
