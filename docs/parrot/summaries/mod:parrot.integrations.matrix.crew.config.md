---
type: Wiki Summary
title: parrot.integrations.matrix.crew.config
id: mod:parrot.integrations.matrix.crew.config
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configuration models for MatrixCrewTransport.
relates_to:
- concept: class:parrot.integrations.matrix.crew.config.CollaborativeConfig
  rel: defines
- concept: class:parrot.integrations.matrix.crew.config.MatrixCrewAgentEntry
  rel: defines
- concept: class:parrot.integrations.matrix.crew.config.MatrixCrewConfig
  rel: defines
---

# `parrot.integrations.matrix.crew.config`

Configuration models for MatrixCrewTransport.

Pydantic v2 models for configuring a multi-agent crew
operating on a Matrix homeserver via the Application Service protocol.

## Classes

- **`MatrixCrewAgentEntry(BaseModel)`** — Configuration for a single agent in the Matrix crew.
- **`CollaborativeConfig(BaseModel)`** — Configuration for collaborative multi-agent investigation sessions.
- **`MatrixCrewConfig(BaseModel)`** — Root configuration for a Matrix multi-agent crew.
