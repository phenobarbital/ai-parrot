---
type: Wiki Summary
title: parrot.bots.flows.agents.orchestrator
id: mod:parrot.bots.flows.agents.orchestrator
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Orchestrator agent for coordinating multiple specialized agents.
relates_to:
- concept: class:parrot.bots.flows.agents.orchestrator.OrchestratorAgent
  rel: defines
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.bots.agent
  rel: references
- concept: mod:parrot.bots.flows.core.result
  rel: references
- concept: mod:parrot.bots.flows.core.storage.memory
  rel: references
- concept: mod:parrot.models.basic
  rel: references
- concept: mod:parrot.models.conference
  rel: references
- concept: mod:parrot.models.responses
  rel: references
- concept: mod:parrot.registry
  rel: references
- concept: mod:parrot.tools.agent
  rel: references
---

# `parrot.bots.flows.agents.orchestrator`

Orchestrator agent for coordinating multiple specialized agents.

Moved from ``parrot.bots.orchestration.agent`` to
``parrot.bots.flows.agents.orchestrator`` (FEAT-143).

Import paths are recalculated for the new package depth
(``flows/agents/`` is two levels deep under ``bots/``).
All class signatures are preserved; no API changes.

## Classes

- **`OrchestratorAgent(BasicAgent)`** — An orchestrator agent that can coordinate multiple specialized agents.
