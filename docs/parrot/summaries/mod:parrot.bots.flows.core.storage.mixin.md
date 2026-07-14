---
type: Wiki Summary
title: parrot.bots.flows.core.storage.mixin
id: mod:parrot.bots.flows.core.storage.mixin
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Flow Primitives — VectorStoreMixin.
relates_to:
- concept: class:parrot.bots.flows.core.storage.mixin.VectorStoreMixin
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.bots.flows.core.result
  rel: references
- concept: mod:parrot.embeddings.base
  rel: references
- concept: mod:parrot.models.crew
  rel: references
---

# `parrot.bots.flows.core.storage.mixin`

Flow Primitives — VectorStoreMixin.

Copied from ``parrot.bots.flow.storage.mixin`` into the shared core
storage location.  Relative imports updated for the new package depth.

Updated (TASK-976): ``AgentResult`` → ``NodeResult`` from ``flows.core.result``.

## Classes

- **`VectorStoreMixin`** — Mixin to add FAISS vector store capabilities to ExecutionMemory.
