---
type: Wiki Entity
title: CrewAgentNode
id: class:parrot.bots.flows.crew.nodes.CrewAgentNode
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Crew-specific node wrapping an agent with dependency metadata.
---

# CrewAgentNode

Defined in [`parrot.bots.flows.crew.nodes`](../summaries/mod:parrot.bots.flows.crew.nodes.md).

```python
class CrewAgentNode(_CoreAgentNode)
```

Crew-specific node wrapping an agent with dependency metadata.

Inherits ``execute()`` (with pre/post hooks) from the core ``AgentNode``.
Overrides ``_build_prompt()`` for crew-specific prompt formatting:
the initial task plus results from upstream dependency agents are
combined into a single natural-language prompt string.

Args:
    agent: The agent this node wraps.
    node_id: Unique identifier for this node in the graph.
    dependencies: Set of node_ids that must complete before this one.
    successors: Set of node_ids that depend on this one.
    fsm: Optional finite state machine for task lifecycle tracking.
