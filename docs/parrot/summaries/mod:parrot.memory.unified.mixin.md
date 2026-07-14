---
type: Wiki Summary
title: parrot.memory.unified.mixin
id: mod:parrot.memory.unified.mixin
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: LongTermMemoryMixin — opt-in unified long-term memory for any bot/agent.
relates_to:
- concept: class:parrot.memory.unified.mixin.LongTermMemoryMixin
  rel: defines
- concept: mod:parrot.memory.episodic.cache
  rel: references
- concept: mod:parrot.memory.episodic.embedding
  rel: references
- concept: mod:parrot.memory.episodic.models
  rel: references
- concept: mod:parrot.memory.episodic.reflection
  rel: references
- concept: mod:parrot.memory.episodic.store
  rel: references
- concept: mod:parrot.memory.unified.manager
  rel: references
- concept: mod:parrot.memory.unified.models
  rel: references
- concept: mod:parrot.skills.store
  rel: references
---

# `parrot.memory.unified.mixin`

LongTermMemoryMixin — opt-in unified long-term memory for any bot/agent.

Wires UnifiedMemoryManager into the agent lifecycle:
- ``_configure_long_term_memory()`` — call from the agent's ``configure()``
- ``get_memory_context()`` — call before LLM invocation to inject context
- ``_post_response_memory_hook()`` — call after response to record interaction

## Classes

- **`LongTermMemoryMixin`** — Single opt-in mixin for long-term memory in any bot/agent.
