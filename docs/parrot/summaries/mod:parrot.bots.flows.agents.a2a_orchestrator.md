---
type: Wiki Summary
title: parrot.bots.flows.agents.a2a_orchestrator
id: mod:parrot.bots.flows.agents.a2a_orchestrator
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: A2A-Enhanced Orchestrator Agent.
relates_to:
- concept: class:parrot.bots.flows.agents.a2a_orchestrator.A2AOrchestratorAgent
  rel: defines
- concept: class:parrot.bots.flows.agents.a2a_orchestrator.DiscoverA2AAgentsInput
  rel: defines
- concept: class:parrot.bots.flows.agents.a2a_orchestrator.ListAvailableA2AAgentsTool
  rel: defines
- concept: mod:parrot.a2a.client
  rel: references
- concept: mod:parrot.a2a.mixin
  rel: references
- concept: mod:parrot.bots.flows.agents.orchestrator
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.bots.flows.agents.a2a_orchestrator`

A2A-Enhanced Orchestrator Agent.

Moved from ``parrot.bots.orchestration.a2a_orchestrator`` to
``parrot.bots.flows.agents.a2a_orchestrator`` (FEAT-143).

Import paths are recalculated for the new package depth.
``OrchestratorAgent`` is now imported from the sibling module
``.orchestrator`` instead of ``.agent``.
All class signatures are preserved; no API changes.

## Classes

- **`DiscoverA2AAgentsInput(AbstractToolArgsSchema)`** — Input schema for ListAvailableA2AAgentsTool.
- **`ListAvailableA2AAgentsTool(AbstractTool)`** — Tool that discovers available A2A agents from specified endpoints.
- **`A2AOrchestratorAgent(A2AClientMixin, OrchestratorAgent)`** — An orchestrator agent that supports both local and remote A2A agents.
