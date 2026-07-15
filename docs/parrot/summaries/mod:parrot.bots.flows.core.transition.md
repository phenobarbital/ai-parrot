---
type: Wiki Summary
title: parrot.bots.flows.core.transition
id: mod:parrot.bots.flows.core.transition
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Flow Primitives — FlowTransition.
relates_to:
- concept: class:parrot.bots.flows.core.transition.FlowTransition
  rel: defines
- concept: mod:parrot.bots.flows.core.fsm
  rel: references
- concept: mod:parrot.bots.flows.core.result
  rel: references
- concept: mod:parrot.bots.flows.core.types
  rel: references
---

# `parrot.bots.flows.core.transition`

Flow Primitives — FlowTransition.

Extracted from ``parrot.bots.flow.fsm.FlowTransition`` into the shared
core module so both ``AgentCrew`` and ``AgentsFlow`` can use the same
transition semantics.

Key changes from the original:
  - ``metadata`` field type changed from ``AgentExecutionInfo`` to
    ``NodeExecutionInfo`` (from ``core.result``).
  - ``build_prompt()`` first argument is ``Any`` (not ``AgentContext``)
    to avoid importing the engine-specific context class.  The method
    still uses ``context.original_query`` via duck-typing.

All activation and prompt-building logic is preserved exactly.

## Classes

- **`FlowTransition`** — Conditional edge between two nodes in a flow/crew DAG.
