---
type: Wiki Summary
title: parrot.bots.flows.core.types
id: mod:parrot.bots.flows.core.types
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Flow Primitives — Types Module.
relates_to:
- concept: class:parrot.bots.flows.core.types.AgentLike
  rel: defines
- concept: class:parrot.bots.flows.core.types.FlowStatus
  rel: defines
---

# `parrot.bots.flows.core.types`

Flow Primitives — Types Module.

Defines the shared type aliases, protocols, and enums used across both
AgentCrew and AgentsFlow orchestration engines.

No imports from ``parrot.bots.*`` or ``parrot.tools.*`` to remain
import-cycle-free.

## Classes

- **`FlowStatus(str, Enum)`** — Overall execution status for a flow/crew run.
- **`AgentLike(Protocol)`** — Structural protocol for any object that can act as an agent node.
