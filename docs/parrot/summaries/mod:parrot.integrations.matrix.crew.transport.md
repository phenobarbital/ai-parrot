---
type: Wiki Summary
title: parrot.integrations.matrix.crew.transport
id: mod:parrot.integrations.matrix.crew.transport
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Matrix crew transport orchestrator.
relates_to:
- concept: class:parrot.integrations.matrix.crew.transport.MatrixCrewTransport
  rel: defines
- concept: mod:parrot.integrations.matrix.appservice
  rel: references
- concept: mod:parrot.integrations.matrix.crew.config
  rel: references
- concept: mod:parrot.integrations.matrix.crew.coordinator
  rel: references
- concept: mod:parrot.integrations.matrix.crew.crew_wrapper
  rel: references
- concept: mod:parrot.integrations.matrix.crew.mention
  rel: references
- concept: mod:parrot.integrations.matrix.crew.registry
  rel: references
- concept: mod:parrot.integrations.matrix.crew.session
  rel: references
- concept: mod:parrot.integrations.matrix.models
  rel: references
---

# `parrot.integrations.matrix.crew.transport`

Matrix crew transport orchestrator.

Top-level lifecycle manager for a Matrix multi-agent crew.
Manages the ``MatrixAppService``, coordinator, registry, and per-agent wrappers.
Supports the async context-manager protocol for clean lifecycle management.

## Classes

- **`MatrixCrewTransport`** — Top-level orchestrator for a Matrix multi-agent crew.
