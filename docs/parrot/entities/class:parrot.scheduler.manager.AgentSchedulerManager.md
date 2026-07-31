---
type: Wiki Entity
title: AgentSchedulerManager
id: class:parrot.scheduler.manager.AgentSchedulerManager
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Manager for scheduling agent operations using APScheduler.
---

# AgentSchedulerManager

Defined in [`parrot.scheduler.manager`](../summaries/mod:parrot.scheduler.manager.md).

```python
class AgentSchedulerManager
```

Manager for scheduling agent operations using APScheduler.

This manager handles:
- Loading schedules from database on startup
- Adding/removing schedules dynamically
- Executing scheduled agent operations
- Safe restart of scheduler

## Methods

- `def define_listeners(self)`
- `def scheduler_status(self, event)`
- `def scheduler_shutdown(self, event)`
- `def job_added(self, event: JobExecutionEvent, *args, **kwargs)`
- `def job_status(self, event: JobExecutionEvent)` — React on Error events from scheduler.
- `def job_success(self, event: JobExecutionEvent)` — Job Success.
- `async def add_schedule(self, agent_name: str, schedule_type: str, schedule_config: Dict[str, Any], prompt: Optional[str]=None, method_name: Optional[str]=None, created_by: Optional[int]=None, created_email: Optional[str]=None, metadata: Optional[Dict]=None, agent_id: Optional[str]=None, *, is_crew: bool=False, send_result: Optional[Dict[str, Any]]=None, success_callback: Optional[Callable]=None, scheduler_type: str='default', callbacks: Optional[List[Dict[str, Any]]]=None) -> AgentSchedule` — Add a new schedule to both database and APScheduler.
- `def register_bot_schedules(self, bot: Any) -> int` — Scan and register @schedule decorated methods for a bot.
- `async def remove_schedule(self, schedule_id: str)` — Remove a schedule from both database and APScheduler.
- `async def load_schedules_from_db(self)` — Load all enabled schedules from database and add to APScheduler.
- `async def restart_scheduler(self)` — Safely restart the scheduler.
- `async def list_jobs(self) -> List[Dict[str, Any]]` — Return every job in the APScheduler JobStore, normalized for the API.
- `async def get_schedule(self, schedule_id: str) -> AgentSchedule`
- `async def list_schedules(self) -> List[AgentSchedule]`
- `async def pause_schedule(self, schedule_id: str) -> AgentSchedule`
- `async def update_schedule(self, schedule_id: str, updates: Dict[str, Any]) -> AgentSchedule`
- `async def delete_schedule(self, schedule_id: str) -> None`
- `def setup(self, app: web.Application) -> web.Application` — Setup scheduler with aiohttp application.
- `async def on_startup(self, app: web.Application, conn: Callable)` — Initialize scheduler on app startup.
- `async def on_shutdown(self, app: web.Application, conn: Callable)` — Cleanup on app shutdown.
- `async def restart_handler(self, request: web.Request)` — HTTP endpoint to restart scheduler.
