---
type: Wiki Entity
title: FlowRelation
id: class:parrot.models.crew_definition.FlowRelation
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Defines a dependency relationship between agents in flow mode.
---

# FlowRelation

Defined in [`parrot.models.crew_definition`](../summaries/mod:parrot.models.crew_definition.md).

```python
class FlowRelation(BaseModel)
```

Defines a dependency relationship between agents in flow mode.

Attributes:
    source: The display name (or list of names) of the agent(s) that must
        complete first.  Must match ``AgentDefinition.name`` when set, or
        ``AgentDefinition.agent_id`` when ``name`` is ``None``.
    target: The display name (or list of names) of the agent(s) that depend
        on ``source`` completion before they can execute.  Same naming
        convention as ``source``.
