---
type: Wiki Entity
title: FlowDefinition
id: class:parrot.bots.flows.flow.definition.FlowDefinition
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Complete definition of an AgentsFlow workflow.
---

# FlowDefinition

Defined in [`parrot.bots.flows.flow.definition`](../summaries/mod:parrot.bots.flows.flow.definition.md).

```python
class FlowDefinition(BaseModel)
```

Complete definition of an AgentsFlow workflow.

This is the root model for JSON serialization. It can be:
- Loaded from file or Redis
- Saved to file or Redis
- Materialized into a runnable AgentsFlow instance

Example:
    >>> definition = FlowDefinition(
    ...     flow="MyFlow",
    ...     nodes=[
    ...         NodeDefinition(id="start", type="start"),
    ...         NodeDefinition(id="worker", type="agent", agent_ref="my_agent"),
    ...     ],
    ...     edges=[
    ...         EdgeDefinition(**{"from": "start", "to": "worker", "condition": "always"})
    ...     ]
    ... )

## Methods

- `def validate_node_ids(self) -> 'FlowDefinition'` — Validate all edge references point to existing node IDs.
