---
type: Wiki Entity
title: AgentExpertise
id: class:parrot.memory.unified.routing.AgentExpertise
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Registry entry for an agent's domain expertise.
---

# AgentExpertise

Defined in [`parrot.memory.unified.routing`](../summaries/mod:parrot.memory.unified.routing.md).

```python
class AgentExpertise(BaseModel)
```

Registry entry for an agent's domain expertise.

Args:
    agent_id: The agent's unique identifier.
    tenant_id: The tenant this agent belongs to (isolation boundary).
    domain_description: Human-readable description of the agent's expertise.
    embedding: Cached embedding of the domain description (None until computed).
