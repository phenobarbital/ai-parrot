---
type: Wiki Summary
title: parrot.integrations.matrix.appservice
id: mod:parrot.integrations.matrix.appservice
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Matrix Application Service for AI-Parrot.
relates_to:
- concept: class:parrot.integrations.matrix.appservice.MatrixAppService
  rel: defines
- concept: mod:parrot.integrations.matrix.events
  rel: references
- concept: mod:parrot.integrations.matrix.models
  rel: references
---

# `parrot.integrations.matrix.appservice`

Matrix Application Service for AI-Parrot.

Wraps mautrix.appservice.AppService to provide:
- Virtual MXIDs for each registered agent
- Event routing from homeserver push to agents
- HookEvent emission compatible with AutonomousOrchestrator
- Lifecycle management (start/stop)

## Classes

- **`MatrixAppService`** — Matrix Application Service for AI-Parrot.
