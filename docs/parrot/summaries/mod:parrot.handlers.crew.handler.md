---
type: Wiki Summary
title: parrot.handlers.crew.handler
id: mod:parrot.handlers.crew.handler
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: REST API Handler for AgentCrew Management.
relates_to:
- concept: class:parrot.handlers.crew.handler.CrewHandler
  rel: defines
- concept: mod:parrot.bots.flows.crew
  rel: references
- concept: mod:parrot.handlers.crew.models
  rel: references
---

# `parrot.handlers.crew.handler`

REST API Handler for AgentCrew Management.

Provides endpoints for creating, managing, and deleting agent crews.

Endpoints:
    PUT /api/v1/crew - Create a new crew
    GET /api/v1/crew - List all crews or get specific crew by name
    DELETE /api/v1/crew - Delete a crew

## Classes

- **`CrewHandler(BaseView)`** — REST API Handler for AgentCrew CRUD operations.
