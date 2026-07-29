---
type: Wiki Summary
title: parrot.integrations.matrix.crew.delegation
id: mod:parrot.integrations.matrix.crew.delegation
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Hybrid tool delegation for Matrix collaborative crew sessions.
relates_to:
- concept: class:parrot.integrations.matrix.crew.delegation.DelegationRequest
  rel: defines
- concept: class:parrot.integrations.matrix.crew.delegation.HybridDelegator
  rel: defines
- concept: mod:parrot.integrations.matrix.appservice
  rel: references
- concept: mod:parrot.integrations.matrix.crew.mention
  rel: references
- concept: mod:parrot.integrations.matrix.crew.registry
  rel: references
- concept: mod:parrot.integrations.matrix.events
  rel: references
---

# `parrot.integrations.matrix.crew.delegation`

Hybrid tool delegation for Matrix collaborative crew sessions.

``HybridDelegator`` bridges the collaborative session layer with the
Matrix custom event layer (``m.parrot.task`` / ``m.parrot.result``),
enabling an agent to request tool execution from a peer agent that has
privileged access.

Flow:
1. Post a visible "Asking @peer to: ..." message in the room.
2. Send a ``m.parrot.task`` custom event via the AppService.
3. Wait for the matching ``m.parrot.result`` custom event (with timeout).
4. Post the result as a visible reply-to the original request message.

## Classes

- **`DelegationRequest(BaseModel)`** — Represents a request to delegate a task to another agent.
- **`HybridDelegator`** — Orchestrates hybrid tool delegation in a Matrix room.
