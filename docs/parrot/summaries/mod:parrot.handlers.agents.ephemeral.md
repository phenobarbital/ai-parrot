---
type: Wiki Summary
title: parrot.handlers.agents.ephemeral
id: mod:parrot.handlers.agents.ephemeral
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: HTTP handler for ephemeral user agent lifecycle (FEAT-149 TASK-1040).
relates_to:
- concept: class:parrot.handlers.agents.ephemeral.EphemeralUserAgentHandler
  rel: defines
---

# `parrot.handlers.agents.ephemeral`

HTTP handler for ephemeral user agent lifecycle (FEAT-149 TASK-1040).

Exposes four routes for the ephemeral agent workflow:

    POST   /api/v1/agents/user/                   — create (fire-and-forget warm-up)
    GET    /api/v1/agents/user/{chatbot_id}/status — warm-up polling
    PUT    /api/v1/agents/user/{chatbot_id}        — promote to persistent
    DELETE /api/v1/agents/user/{chatbot_id}        — discard / delete

All routes enforce per-user ownership via session-based ``user_id``.
Routes are wired in TASK-1041 (route registration).

## Classes

- **`EphemeralUserAgentHandler(BaseView)`** — Handler for the ephemeral user agent lifecycle.
