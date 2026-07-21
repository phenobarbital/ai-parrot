---
type: Wiki Entity
title: NodeDefinition
id: class:parrot.bots.flows.flow.definition.NodeDefinition
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Definition of a node in the flow.
---

# NodeDefinition

Defined in [`parrot.bots.flows.flow.definition`](../summaries/mod:parrot.bots.flows.flow.definition.md).

```python
class NodeDefinition(BaseModel)
```

Definition of a node in the flow.

Node types:
- start: Entry point, no agent_ref required
- end: Terminal point, no agent_ref required
- agent: Wraps a registered agent, requires agent_ref
- decision: Multi-agent voting/consensus
- interactive_decision: Human-in-the-loop choice
- human: Full HITL escalation

## Methods

- `def validate_agent_ref(self) -> 'NodeDefinition'` — Agent nodes require agent_ref.
