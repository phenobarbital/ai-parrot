---
type: Wiki Summary
title: parrot.handlers.config_handler
id: mod:parrot.handlers.config_handler
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: REST API Handler for BotConfig Management.
relates_to:
- concept: class:parrot.handlers.config_handler.BotConfigHandler
  rel: defines
- concept: mod:parrot.registry
  rel: references
---

# `parrot.handlers.config_handler`

REST API Handler for BotConfig Management.

Provides CRUD endpoints for managing agent configurations
via the AgentRegistry and BotConfigStorage (Redis).

Endpoints:
    GET    /api/v1/agents/config              — list all configs (optionally ?category=X)
    GET    /api/v1/agents/config/{agent_name} — get single config
    POST   /api/v1/agents/config/{agent_name} — update existing config
    PUT    /api/v1/agents/config              — insert new config (Redis)
    DELETE /api/v1/agents/config/{agent_name} — delete Redis-backed config
    PATCH  /api/v1/agents/config/{agent_name} — partial update of config fields

## Classes

- **`BotConfigHandler(BaseView)`** — REST API Handler for BotConfig CRUD operations.
