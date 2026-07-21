---
type: Wiki Summary
title: parrot.memory.unified.manager
id: mod:parrot.memory.unified.manager
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Unified Memory Manager — coordinates all long-term memory subsystems.
relates_to:
- concept: class:parrot.memory.unified.manager.SkillRegistry
  rel: defines
- concept: class:parrot.memory.unified.manager.UnifiedMemoryManager
  rel: defines
- concept: mod:parrot.memory.abstract
  rel: references
- concept: mod:parrot.memory.episodic.models
  rel: references
- concept: mod:parrot.memory.episodic.store
  rel: references
- concept: mod:parrot.memory.unified.context
  rel: references
- concept: mod:parrot.memory.unified.models
  rel: references
- concept: mod:parrot.memory.unified.routing
  rel: references
---

# `parrot.memory.unified.manager`

Unified Memory Manager — coordinates all long-term memory subsystems.

Orchestrates parallel retrieval from episodic memory, skill registry, and
conversation memory, then passes results through ContextAssembler for
token-budgeted context assembly.

## Classes

- **`SkillRegistry(Protocol)`** — Structural protocol for skill registries.
- **`UnifiedMemoryManager`** — Coordinates episodic memory, skill registry, and conversation memory.
