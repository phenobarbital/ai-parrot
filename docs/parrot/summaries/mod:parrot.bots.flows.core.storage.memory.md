---
type: Wiki Summary
title: parrot.bots.flows.core.storage.memory
id: mod:parrot.bots.flows.core.storage.memory
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Flow Primitives — ExecutionMemory.
relates_to:
- concept: class:parrot.bots.flows.core.storage.memory.ExecutionMemory
  rel: defines
- concept: mod:parrot.bots.flows.core.result
  rel: references
- concept: mod:parrot.bots.flows.core.storage.mixin
  rel: references
---

# `parrot.bots.flows.core.storage.memory`

Flow Primitives — ExecutionMemory.

Copied from ``parrot.bots.flow.storage.memory`` into the shared core
storage location.  Relative imports updated for the new package depth.

Updated (TASK-976): ``AgentResult`` → ``NodeResult`` from ``flows.core.result``.

## Classes

- **`ExecutionMemory(VectorStoreMixin)`** — In-memory storage for execution history.
