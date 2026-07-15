---
type: Wiki Entity
title: DelegationRequest
id: class:parrot.integrations.matrix.crew.delegation.DelegationRequest
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Represents a request to delegate a task to another agent.
---

# DelegationRequest

Defined in [`parrot.integrations.matrix.crew.delegation`](../summaries/mod:parrot.integrations.matrix.crew.delegation.md).

```python
class DelegationRequest(BaseModel)
```

Represents a request to delegate a task to another agent.

Args:
    requester_name: Agent name of the delegating agent.
    target_agent: Agent name of the peer who will execute the task.
    task_description: Human-readable description of the delegated task.
    room_id: Matrix room where the delegation happens.
    context: Optional shared context or reference for the task.
