---
type: Wiki Entity
title: CrewHandler
id: class:parrot.handlers.crew.handler.CrewHandler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: REST API Handler for AgentCrew CRUD operations.
---

# CrewHandler

Defined in [`parrot.handlers.crew.handler`](../summaries/mod:parrot.handlers.crew.handler.md).

```python
class CrewHandler(BaseView)
```

REST API Handler for AgentCrew CRUD operations.

This handler manages the lifecycle of crew definitions (Create, Read, Update, Delete).
Execution and runtime management are handled by CrewExecutionHandler.

## Methods

- `def bot_manager(self)` — Get bot manager.
- `def bot_manager(self, value)` — Set bot manager.
- `def configure(cls, app: WebApp=None, path: str=None, **kwargs) -> WebApp` — configure.
- `async def upload(self)` — Upload a crew definition from a JSON file.
- `async def put(self)` — Create a new AgentCrew or update an existing one.
- `async def get(self)` — Get crew information.
- `async def delete(self)` — Delete a crew.
