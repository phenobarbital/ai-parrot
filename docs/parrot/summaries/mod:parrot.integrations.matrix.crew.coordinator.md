---
type: Wiki Summary
title: parrot.integrations.matrix.crew.coordinator
id: mod:parrot.integrations.matrix.crew.coordinator
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Matrix crew coordinator bot — manages pinned status board.
relates_to:
- concept: class:parrot.integrations.matrix.crew.coordinator.MatrixCoordinator
  rel: defines
- concept: mod:parrot.integrations.matrix.crew.registry
  rel: references
---

# `parrot.integrations.matrix.crew.coordinator`

Matrix crew coordinator bot — manages pinned status board.

Maintains a pinned message in the general room that shows the live status
of all agents in the crew (ready / busy / offline).  The board is updated
on every agent join, leave, or status-change event, subject to a
configurable rate limit.

## Classes

- **`MatrixCoordinator`** — Manages the pinned status board in the general room.
