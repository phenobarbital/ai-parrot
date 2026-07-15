---
type: Wiki Summary
title: parrot.bots.flows.crew.nodes
id: mod:parrot.bots.flows.crew.nodes
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Crew-specific node type for AgentCrew orchestration.
relates_to:
- concept: class:parrot.bots.flows.crew.nodes.CrewAgentNode
  rel: defines
- concept: mod:parrot.bots.flows.core.context
  rel: references
- concept: mod:parrot.bots.flows.core.node
  rel: references
- concept: mod:parrot.bots.flows.core.types
  rel: references
---

# `parrot.bots.flows.crew.nodes`

Crew-specific node type for AgentCrew orchestration.

Defines ``CrewAgentNode``, extracted from ``parrot.bots.orchestration.crew``
(formerly ``_CrewAgentNode``), with the public name and updated imports for
its new location under ``parrot.bots.flows.crew``.

The node subclasses ``AgentNode`` from ``flows.core.node`` and overrides
``_build_prompt`` to apply crew-specific formatting that combines the
initial task with results from upstream dependency agents.

FEAT-163 changes:
    - Converted from ``@dataclass`` to Pydantic ``BaseModel`` subclass
      (inherits frozen + arbitrary_types_allowed from the new ``AgentNode``).
    - ``_format_prompt(input_data)`` renamed/replaced by ``_build_prompt(ctx, deps)``
      override (same formatting logic, new signature matching the FEAT-163 contract).
    - ``execute_in_context(context, timeout)`` removed; callers use the
      inherited ``execute(ctx, deps, **kwargs)`` directly.

## Classes

- **`CrewAgentNode(_CoreAgentNode)`** — Crew-specific node wrapping an agent with dependency metadata.
