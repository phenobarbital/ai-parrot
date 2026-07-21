---
type: Wiki Summary
title: parrot.bots.flows.crew.crew
id: mod:parrot.bots.flows.crew.crew
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: AgentCrew — Parallel, Sequential, Flow, and Loop-Based Execution.
relates_to:
- concept: class:parrot.bots.flows.crew.crew.AgentCrew
  rel: defines
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.bots.agent
  rel: references
- concept: mod:parrot.bots.flows
  rel: references
- concept: mod:parrot.bots.flows.core.context
  rel: references
- concept: mod:parrot.bots.flows.core.fsm
  rel: references
- concept: mod:parrot.bots.flows.core.result
  rel: references
- concept: mod:parrot.bots.flows.core.storage
  rel: references
- concept: mod:parrot.bots.flows.core.storage.backends
  rel: references
- concept: mod:parrot.bots.flows.core.storage.synthesis
  rel: references
- concept: mod:parrot.bots.flows.core.types
  rel: references
- concept: mod:parrot.bots.flows.crew.nodes
  rel: references
- concept: mod:parrot.bots.flows.crew.result_infographic
  rel: references
- concept: mod:parrot.bots.flows.crew.tool_node
  rel: references
- concept: mod:parrot.bots.flows.result_agent
  rel: references
- concept: mod:parrot.bots.flows.tools
  rel: references
- concept: mod:parrot.bots.prompts.layers
  rel: references
- concept: mod:parrot.clients
  rel: references
- concept: mod:parrot.clients.factory
  rel: references
- concept: mod:parrot.clients.google
  rel: references
- concept: mod:parrot.models.crew_definition
  rel: references
- concept: mod:parrot.models.responses
  rel: references
- concept: mod:parrot.models.status
  rel: references
- concept: mod:parrot.registry
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot.tools.agent
  rel: references
- concept: mod:parrot.tools.manager
  rel: references
---

# `parrot.bots.flows.crew.crew`

AgentCrew — Parallel, Sequential, Flow, and Loop-Based Execution.

Moved from ``parrot.bots.orchestration.crew`` to ``parrot.bots.flows.crew``
(FEAT-143). All result models have been migrated:
  - ``CrewResult`` → ``FlowResult``
  - ``AgentExecutionInfo`` → ``NodeExecutionInfo``
  - ``build_agent_metadata`` → ``build_node_metadata``
  - ``AgentResult`` → ``NodeResult``

The original ``orchestration/crew.py`` is left in place for review.

TASK-980: ``AgentContext`` removed; sequential/loop/parallel modes now use
``FlowContext`` for execution state tracking.

Module-level constant ``_INTERNAL_SHARED_KEYS`` lists keys that are placed
in ``FlowContext.shared_data`` for framework bookkeeping and must NOT be
forwarded as kwargs to agent calls.

## Classes

- **`AgentCrew(PersistenceMixin, SynthesisMixin)`** — Enhanced AgentCrew supporting multiple execution modes.
