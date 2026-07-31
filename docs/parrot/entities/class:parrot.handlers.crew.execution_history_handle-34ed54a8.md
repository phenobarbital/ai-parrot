---
type: Wiki Entity
title: CrewExecutionHistoryHandler
id: class:parrot.handlers.crew.execution_history_handler.CrewExecutionHistoryHandler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: REST API Handler for saved crew execution history, replay, and scheduling.
---

# CrewExecutionHistoryHandler

Defined in [`parrot.handlers.crew.execution_history_handler`](../summaries/mod:parrot.handlers.crew.execution_history_handler.md).

```python
class CrewExecutionHistoryHandler(BaseView)
```

REST API Handler for saved crew execution history, replay, and scheduling.

Thin HTTP layer over ``SavedExecutionService`` — all orchestration logic
(storage reads, crew resolution, scheduler calls) lives in the service;
this handler only parses requests, calls the service, and maps
exceptions to HTTP responses.

## Methods

- `def service(self) -> SavedExecutionService` — Lazily build the ``SavedExecutionService`` from app-level dependencies.
- `def configure(cls, app: WebApp=None, path: str=None, **kwargs) -> WebApp`
- `async def get(self)` — List executions, or return execution detail if `execution_id` is set.
- `async def post(self)` — Replay or schedule a saved execution, per the `{action}` path segment.
- `async def delete(self)` — Delete a saved execution.
