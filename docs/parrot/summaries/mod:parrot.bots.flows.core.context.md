---
type: Wiki Summary
title: parrot.bots.flows.core.context
id: mod:parrot.bots.flows.core.context
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Flow Primitives — FlowContext.
relates_to:
- concept: class:parrot.bots.flows.core.context.AgentNotFoundError
  rel: defines
- concept: class:parrot.bots.flows.core.context.FlowContext
  rel: defines
- concept: mod:parrot.bots.flows.core.result
  rel: references
- concept: mod:parrot.bots.flows.core.types
  rel: references
- concept: mod:parrot.core.events.lifecycle.trace
  rel: references
- concept: mod:parrot.registry.registry
  rel: references
---

# `parrot.bots.flows.core.context`

Flow Primitives — FlowContext.

Shared workflow execution state tracker used by both ``AgentCrew``
and ``AgentsFlow`` orchestration engines.

Extracted from ``parrot.bots.orchestration.crew.FlowContext`` with
node-centric renaming and backward-compat aliases.

Primary names:
    ``node_metadata`` — execution metadata keyed by node_id.
    ``get_input_for_node()`` — assemble input dict for a node.

Backward-compat aliases (forwarded to the primary methods):
    ``agent_metadata`` — property alias for ``node_metadata``.
    ``get_input_for_agent()`` — alias for ``get_input_for_node()``.

FEAT-163 additions:
    ``agent_registry`` — optional ``AgentRegistry`` bound to the context.
    ``resolve_agent(agent_ref)`` — resolve an agent reference to a live agent
        via the bound registry; raises ``AgentNotFoundError`` on miss.
    ``AgentNotFoundError`` — raised when ``resolve_agent`` cannot find the
        requested agent in the registry.

## Classes

- **`AgentNotFoundError(LookupError)`** — Raised when ``FlowContext.resolve_agent`` cannot find the requested agent.
- **`FlowContext`** — Execution state tracker for a single flow/crew run.
