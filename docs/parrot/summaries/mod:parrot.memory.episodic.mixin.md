---
type: Wiki Summary
title: parrot.memory.episodic.mixin
id: mod:parrot.memory.episodic.mixin
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: EpisodicMemoryMixin for AbstractBot integration.
relates_to:
- concept: class:parrot.memory.episodic.mixin.EpisodicMemoryMixin
  rel: defines
- concept: mod:parrot.conf
  rel: references
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
- concept: mod:parrot.memory.episodic.tools
  rel: references
---

# `parrot.memory.episodic.mixin`

EpisodicMemoryMixin for AbstractBot integration.

Provides automatic episodic memory recording and context injection
as an opt-in mixin for bot classes. Hooks into the ask() flow to:
1. Inject episodic context (warnings, preferences) pre-LLM.
2. Record tool executions as episodes post-tool.
3. Record significant conversations post-ask.

## Classes

- **`EpisodicMemoryMixin`** — Mixin that adds automatic episodic memory to bots.
