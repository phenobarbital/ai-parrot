---
type: Wiki Entity
title: ChatbotHandler
id: class:parrot.handlers.bots.ChatbotHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Unified agent management handler.
---

# ChatbotHandler

Defined in [`parrot.handlers.bots`](../summaries/mod:parrot.handlers.bots.md).

```python
class ChatbotHandler(_PBACHandlerMixin, AbstractModel)
```

Unified agent management handler.

Manages agents from both PostgreSQL (BotModel) and
AgentRegistry (YAML/BotConfig) with BotManager integration.

Endpoints (configured via AbstractModel.configure):
    GET    /api/v1/bots            — list all agents (DB + registry)
    GET    /api/v1/bots/{id}       — single agent by name
    PUT    /api/v1/bots            — create new agent
    POST   /api/v1/bots/{id}       — update existing agent
    DELETE /api/v1/bots/{id}       — delete DB agent only

## Methods

- `async def get(self)` — Return agents from database and AgentRegistry.
- `async def put(self)` — Create a new agent.
- `async def post(self)` — Update an existing agent.
- `async def delete(self)` — Delete a database-backed agent.
