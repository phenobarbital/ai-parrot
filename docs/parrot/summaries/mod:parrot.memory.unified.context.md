---
type: Wiki Summary
title: parrot.memory.unified.context
id: mod:parrot.memory.unified.context
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Context assembler for unified memory — priority-based token budgeting.
relates_to:
- concept: class:parrot.memory.unified.context.ContextAssembler
  rel: defines
- concept: mod:parrot.memory.unified.models
  rel: references
---

# `parrot.memory.unified.context`

Context assembler for unified memory — priority-based token budgeting.

Assembles context from multiple memory subsystems (episodic, skills,
conversation) while respecting a configurable token budget.

## Classes

- **`ContextAssembler`** — Assembles context from multiple sources within a token budget.
