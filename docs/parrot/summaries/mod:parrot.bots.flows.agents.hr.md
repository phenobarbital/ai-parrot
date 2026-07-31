---
type: Wiki Summary
title: parrot.bots.flows.agents.hr
id: mod:parrot.bots.flows.agents.hr
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: HR-specific orchestrator and crew factories.
relates_to:
- concept: class:parrot.bots.flows.agents.hr.EmployeeDataAgent
  rel: defines
- concept: class:parrot.bots.flows.agents.hr.HRAgentFactory
  rel: defines
- concept: class:parrot.bots.flows.agents.hr.RAGHRAgent
  rel: defines
- concept: mod:parrot.bots.agent
  rel: references
- concept: mod:parrot.bots.flows.agents.orchestrator
  rel: references
- concept: mod:parrot.bots.flows.crew
  rel: references
- concept: mod:parrot.stores.abstract
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot.tools.manager
  rel: references
---

# `parrot.bots.flows.agents.hr`

HR-specific orchestrator and crew factories.

Moved from ``parrot.bots.orchestration.hr`` to
``parrot.bots.flows.agents.hr`` (FEAT-143).

Import paths are recalculated for the new package depth:
- ``OrchestratorAgent`` now imported from ``.orchestrator``
- ``AgentCrew`` now imported from ``..crew`` (flows.crew package)
All class signatures are preserved; no API changes.

## Classes

- **`HRAgentFactory`** — Factory for creating HR-specific agent orchestration systems.
- **`RAGHRAgent(BasicAgent)`** — HR Agent with RAG capabilities using the existing vector store system.
- **`EmployeeDataAgent(BasicAgent)`** — Agent specialized in employee profile and organizational data.
