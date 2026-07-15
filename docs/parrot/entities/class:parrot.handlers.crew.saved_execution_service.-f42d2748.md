---
type: Wiki Entity
title: SavedExecutionService
id: class:parrot.handlers.crew.saved_execution_service.SavedExecutionService
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Orchestration layer for execution history, replay, and scheduling.
---

# SavedExecutionService

Defined in [`parrot.handlers.crew.saved_execution_service`](../summaries/mod:parrot.handlers.crew.saved_execution_service.md).

```python
class SavedExecutionService
```

Orchestration layer for execution history, replay, and scheduling.

Thin coordination layer between the HTTP handler and the storage /
bot-manager / scheduler-manager backends. Contains no HTTP-specific
logic — callers (handlers) translate raised exceptions into responses.

Attributes:
    storage: The ``ResultStorage`` backend used for read/delete.
    bot_manager: Resolves crews by name/id for replay (``get_crew()``).
    scheduler_manager: Creates APScheduler jobs for scheduling.

## Methods

- `async def list_executions(self, tenant: str, user_id: str, filters: Optional[ExecutionFilter]=None, limit: int=20, offset: int=0) -> tuple[list[dict], int]` — List saved executions for a tenant/user, with optional filters.
- `async def get_execution(self, tenant: str, user_id: str, execution_id: str) -> Optional[dict]` — Retrieve a single saved execution by id.
- `async def replay_execution(self, tenant: str, user_id: str, execution_id: str) -> dict` — Re-run a saved execution's prompt against the crew's current config.
- `async def schedule_execution(self, tenant: str, user_id: str, execution_id: str, schedule_config: ScheduleRequest) -> dict` — Create a recurring/one-off schedule from a saved execution.
- `async def delete_execution(self, tenant: str, user_id: str, execution_id: str) -> bool` — Delete a saved execution.
