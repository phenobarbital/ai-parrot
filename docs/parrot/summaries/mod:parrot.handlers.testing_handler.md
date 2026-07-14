---
type: Wiki Summary
title: parrot.handlers.testing_handler
id: mod:parrot.handlers.testing_handler
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: REST API Handler for Agent Configuration Testing.
relates_to:
- concept: class:parrot.handlers.testing_handler.BotConfigTestHandler
  rel: defines
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.manager
  rel: references
---

# `parrot.handlers.testing_handler`

REST API Handler for Agent Configuration Testing.

Provides session-based agent testing via PUT/POST/DELETE.

Endpoints:
    PUT    /api/v1/agents/test/{agent_name} — create test agent session
    POST   /api/v1/agents/test/{agent_name} — send query to test agent
    DELETE /api/v1/agents/test/{agent_name} — stop test session

## Classes

- **`BotConfigTestHandler(BaseView)`** — Handler for testing agent configurations via ephemeral sessions.
