---
type: Wiki Entity
title: CrewExecutionHandler
id: class:parrot.handlers.crew.execution_handler.CrewExecutionHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: REST API Handler for running Crew execution and monitoring.
---

# CrewExecutionHandler

Defined in [`parrot.handlers.crew.execution_handler`](../summaries/mod:parrot.handlers.crew.execution_handler.md).

```python
class CrewExecutionHandler(BaseView)
```

REST API Handler for running Crew execution and monitoring.

Responsibilities:
- Execute Crews (POST /api/v1/crews)
- Monitor Job Status (PATCH /api/v1/crews?job_id=...)
- List Active/Completed Jobs (GET /api/v1/crews?mode=...)
- Detailed Agent Status (GET /api/v1/crews/{job_id}/{crew_id})
- Interact with Running Crews (POST /api/v1/crews/{job_id}/{crew_id}/ask)

## Methods

- `def bot_manager(self)` — Get bot manager.
- `async def configure_job_manager(app: WebApp)` — Configure and start job manager.
- `async def start_cleanup_task(app: WebApp)` — Start background cleanup for finished jobs/crews if needed.
- `def configure(cls, app: WebApp=None, path: str=None, **kwargs) -> WebApp`
- `async def get(self)` — Handle GET requests:
- `async def patch(self)` — Handle PATCH requests:
- `async def put(self)` — Handle PUT requests:
- `async def post(self)` — Handle POST requests:
- `async def execute_crew(self, data: Dict[str, Any])` — Logic to initialize and run a crew execution job.
