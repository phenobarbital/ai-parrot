---
type: Wiki Summary
title: parrot.manager.ephemeral
id: mod:parrot.manager.ephemeral
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Ephemeral user agent lifecycle models and registry.
relates_to:
- concept: class:parrot.manager.ephemeral.EphemeralAgentStatus
  rel: defines
- concept: class:parrot.manager.ephemeral.EphemeralRegistry
  rel: defines
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.mcp.client
  rel: references
- concept: mod:parrot.mcp.integration
  rel: references
- concept: mod:parrot.stores.faiss_store
  rel: references
- concept: mod:parrot.stores.models
  rel: references
---

# `parrot.manager.ephemeral`

Ephemeral user agent lifecycle models and registry.

Provides:
- ``EphemeralAgentStatus`` — Pydantic model tracking warm-up state for an
  ephemeral (in-memory-only) user bot.
- ``EphemeralRegistry`` — In-memory dict-backed store for active ephemeral
  statuses, with per-user ownership checks and TTL expiration helpers.
- ``_warm_up`` — background coroutine that drives an ephemeral bot through
  the configure → MCP validate → RAG build pipeline.

All types are consumed by ``BotManager`` (Module 2 / TASK-1035).

## Classes

- **`EphemeralAgentStatus(BaseModel)`** — Live warm-up state for an ephemeral user bot.
- **`EphemeralRegistry`** — In-memory registry of active ephemeral bots.
