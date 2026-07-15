---
type: Wiki Summary
title: parrot.bots.database.agent
id: mod:parrot.bots.database.agent
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: DatabaseAgent — LLM-backed unified agent with structured output.
relates_to:
- concept: class:parrot.bots.database.agent.DatabaseAgent
  rel: defines
- concept: mod:parrot.bots.agent
  rel: references
- concept: mod:parrot.bots.database.cache
  rel: references
- concept: mod:parrot.bots.database.models
  rel: references
- concept: mod:parrot.bots.database.prompts
  rel: references
- concept: mod:parrot.bots.database.retries
  rel: references
- concept: mod:parrot.bots.database.router
  rel: references
- concept: mod:parrot.bots.database.toolkits
  rel: references
- concept: mod:parrot.bots.database.toolkits.base
  rel: references
- concept: mod:parrot.bots.prompts
  rel: references
- concept: mod:parrot.models
  rel: references
- concept: mod:parrot.models.outputs
  rel: references
- concept: mod:parrot.stores.abstract
  rel: references
---

# `parrot.bots.database.agent`

DatabaseAgent — LLM-backed unified agent with structured output.

Inherits from BasicAgent, delegates all database operations to toolkits,
and uses QueryResponse structured output for every ask() call.

## Classes

- **`DatabaseAgent(BasicAgent)`** — Unified database agent backed by BasicAgent + QueryResponse structured output.
