---
type: Wiki Summary
title: parrot.integrations.matrix.crew.crew_wrapper
id: mod:parrot.integrations.matrix.crew.crew_wrapper
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Per-agent message handler for the Matrix multi-agent crew.
relates_to:
- concept: class:parrot.integrations.matrix.crew.crew_wrapper.MatrixCrewAgentWrapper
  rel: defines
- concept: mod:parrot.integrations.matrix.appservice
  rel: references
- concept: mod:parrot.integrations.matrix.crew.config
  rel: references
- concept: mod:parrot.integrations.matrix.crew.coordinator
  rel: references
- concept: mod:parrot.integrations.matrix.crew.registry
  rel: references
- concept: mod:parrot.manager
  rel: references
---

# `parrot.integrations.matrix.crew.crew_wrapper`

Per-agent message handler for the Matrix multi-agent crew.

Each ``MatrixCrewAgentWrapper`` handles messages directed at a specific agent:
typing indicators, BotManager resolution, response sending (with optional
streaming / chunking), and coordinator status notifications.

## Classes

- **`MatrixCrewAgentWrapper`** — Per-agent handler for incoming Matrix crew messages.
