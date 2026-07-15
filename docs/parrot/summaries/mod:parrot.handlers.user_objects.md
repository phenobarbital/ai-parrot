---
type: Wiki Summary
title: parrot.handlers.user_objects
id: mod:parrot.handlers.user_objects
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: UserObjectsHandler - Session-Scoped User Object Management
relates_to:
- concept: class:parrot.handlers.user_objects.UserObjectsHandler
  rel: defines
- concept: mod:parrot.auth.credentials
  rel: references
- concept: mod:parrot.auth.oauth2.persistence
  rel: references
- concept: mod:parrot.auth.oauth2.registry
  rel: references
- concept: mod:parrot.bots.data
  rel: references
- concept: mod:parrot.mcp.integration
  rel: references
- concept: mod:parrot.models
  rel: references
- concept: mod:parrot.tools.dataset_manager
  rel: references
- concept: mod:parrot.tools.manager
  rel: references
---

# `parrot.handlers.user_objects`

UserObjectsHandler - Session-Scoped User Object Management
===========================================================
Manages session-scoped ToolManager and DatasetManager instances for users.

Extracted from AgentTalk to reduce complexity and centralize user object
configuration logic.

## Classes

- **`UserObjectsHandler`** — Manages session-scoped ToolManager and DatasetManager instances.
