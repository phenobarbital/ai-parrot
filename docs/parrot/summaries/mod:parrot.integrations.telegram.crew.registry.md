---
type: Wiki Summary
title: parrot.integrations.telegram.crew.registry
id: mod:parrot.integrations.telegram.crew.registry
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Thread-safe in-memory registry of active agents in a crew.
relates_to:
- concept: class:parrot.integrations.telegram.crew.registry.CrewRegistry
  rel: defines
- concept: mod:parrot.integrations.telegram.crew.agent_card
  rel: references
---

# `parrot.integrations.telegram.crew.registry`

Thread-safe in-memory registry of active agents in a crew.

Provides CRUD operations on AgentCard entries and resolution
by Telegram username or agent name.

## Classes

- **`CrewRegistry`** — Thread-safe in-memory registry tracking active agents in the crew.
