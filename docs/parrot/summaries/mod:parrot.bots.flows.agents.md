---
type: Wiki Summary
title: parrot.bots.flows.agents
id: mod:parrot.bots.flows.agents
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: parrot.bots.flows.agents — orchestrator agents sub-package.
relates_to:
- concept: mod:parrot.bots.flows
  rel: references
---

# `parrot.bots.flows.agents`

parrot.bots.flows.agents — orchestrator agents sub-package.

Exports the orchestrator agents moved from ``parrot.bots.orchestration``
as part of FEAT-143 flows consolidation.

Usage::

    from parrot.bots.flows.agents import (
        OrchestratorAgent,
        A2AOrchestratorAgent,
        ListAvailableA2AAgentsTool,
        HRAgentFactory,
        RAGHRAgent,
        EmployeeDataAgent,
    )
