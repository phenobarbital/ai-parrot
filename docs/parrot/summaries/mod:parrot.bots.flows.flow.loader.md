---
type: Wiki Summary
title: parrot.bots.flows.flow.loader
id: mod:parrot.bots.flows.flow.loader
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: FlowLoader — Load, save, and materialize FlowDefinition instances.
relates_to:
- concept: class:parrot.bots.flows.flow.loader.FlowLoader
  rel: defines
- concept: mod:parrot.bots.flows.core.node
  rel: references
- concept: mod:parrot.bots.flows.flow.actions
  rel: references
- concept: mod:parrot.bots.flows.flow.cel_evaluator
  rel: references
- concept: mod:parrot.bots.flows.flow.definition
  rel: references
- concept: mod:parrot.bots.flows.flow.flow
  rel: references
- concept: mod:parrot.conf
  rel: references
---

# `parrot.bots.flows.flow.loader`

FlowLoader — Load, save, and materialize FlowDefinition instances.

Handles persistence (file I/O, Redis) and materialization (JSON → runnable
AgentsFlow). Combines FlowDefinition, CELPredicateEvaluator, ACTION_REGISTRY,
and AgentsFlow into a cohesive API.

Example::

    >>> definition = FlowLoader.load_from_file("my_flow.json")
    >>> flow = FlowLoader.to_agents_flow(definition, extra_agents={"worker": my_agent})
    >>> result = await flow.run_flow("Hello")

## Classes

- **`FlowLoader`** — Load, save, and materialize FlowDefinition instances.
