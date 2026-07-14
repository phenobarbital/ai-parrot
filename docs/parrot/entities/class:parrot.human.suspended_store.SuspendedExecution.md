---
type: Wiki Entity
title: SuspendedExecution
id: class:parrot.human.suspended_store.SuspendedExecution
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Tool-loop state blob for a suspended HITL interaction.
---

# SuspendedExecution

Defined in [`parrot.human.suspended_store`](../summaries/mod:parrot.human.suspended_store.md).

```python
class SuspendedExecution(BaseModel)
```

Tool-loop state blob for a suspended HITL interaction.

Persisted to ``hitl:suspended:{interaction_id}`` in Redis with a TTL
aligned to ``hitl:interaction:{id}`` (via
:meth:`HumanInteractionManager._compute_ttl`).  Rehydrated by the resume
branch of ``AgentTalk.post`` so ``agent.resume()`` can inject the human's
answer as the ``tool_result`` of the pending ``ask_human`` call.

Attributes:
    interaction_id: UUID of the pending :class:`~parrot.human.models.HumanInteraction`.
    session_id: Agent session identifier (forwarded to ``agent.resume``).
    user_id: Authenticated user who initiated the chat request.
    agent_name: Name of the agent that was running when the interrupt fired.
    tool_call_id: LLM tool-call ID of the pending ``ask_human`` invocation.
    messages: Provider-shaped message history at the point of suspension.
        Stored as-is; ``agent.resume`` replays them without re-encoding.
    created_at: UTC timestamp of when this record was created.
