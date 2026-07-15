---
type: Wiki Summary
title: parrot.handlers.agents.users
id: mod:parrot.handlers.agents.users
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: HTTP handler for user-defined bots — ``/api/v1/user_agents``.
relates_to:
- concept: class:parrot.handlers.agents.users.UserAgentHandler
  rel: defines
- concept: mod:parrot.handlers.models
  rel: references
- concept: mod:parrot.manager.manager
  rel: references
- concept: mod:parrot.tools.filemanager
  rel: references
---

# `parrot.handlers.agents.users`

HTTP handler for user-defined bots — ``/api/v1/user_agents``.

Methods:
    PUT    /api/v1/user_agents               — create
    PATCH  /api/v1/user_agents/{chatbot_id}  — partial update
    GET    /api/v1/user_agents               — list current user's bots
    GET    /api/v1/user_agents/{chatbot_id}  — fetch one
    DELETE /api/v1/user_agents/{chatbot_id}  — delete row + S3 docs

``mcp_config`` and ``tools_config`` may carry credentials. They are stored as
AES-GCM encrypted blobs (transparent to the handler via ``UserBotModel``
accessors) and credential-shaped keys are redacted on GET responses.

## Classes

- **`UserAgentHandler(BaseView)`** — CRUD handler for per-user bots.
