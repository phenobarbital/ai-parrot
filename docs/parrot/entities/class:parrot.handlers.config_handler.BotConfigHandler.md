---
type: Wiki Entity
title: BotConfigHandler
id: class:parrot.handlers.config_handler.BotConfigHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: REST API Handler for BotConfig CRUD operations.
---

# BotConfigHandler

Defined in [`parrot.handlers.config_handler`](../summaries/mod:parrot.handlers.config_handler.md).

```python
class BotConfigHandler(BaseView)
```

REST API Handler for BotConfig CRUD operations.

## Methods

- `def registry(self) -> AgentRegistry` — Get AgentRegistry from the app.
- `def storage(self) -> BotConfigStorage` — Get BotConfigStorage from the app.
- `async def get(self) -> web.Response` — GET handler.
- `async def post(self) -> web.Response` — Update an existing agent config.
- `async def put(self) -> web.Response` — Insert a new agent config into Redis and register in runtime.
- `async def delete(self) -> web.Response` — Delete a Redis-backed agent config.
- `async def patch(self) -> web.Response` — Partially update fields on an existing agent config.
