---
type: Wiki Summary
title: parrot.integrations.matrix.crew.registry
id: mod:parrot.integrations.matrix.crew.registry
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Thread-safe in-memory agent registry for Matrix multi-agent crew.
relates_to:
- concept: class:parrot.integrations.matrix.crew.registry.MatrixAgentCard
  rel: defines
- concept: class:parrot.integrations.matrix.crew.registry.MatrixCrewRegistry
  rel: defines
---

# `parrot.integrations.matrix.crew.registry`

Thread-safe in-memory agent registry for Matrix multi-agent crew.

Provides CRUD operations on ``MatrixAgentCard`` entries and resolution
by agent name or full MXID.

## Classes

- **`MatrixAgentCard(BaseModel)`** — Agent identity and runtime status for a Matrix crew.
- **`MatrixCrewRegistry`** — Thread-safe in-memory registry tracking agent status in a Matrix crew.
