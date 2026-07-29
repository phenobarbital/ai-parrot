---
type: Wiki Entity
title: AgentLedgerState
id: class:parrot.autonomous.ledger.AgentLedgerState
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Read projection of an agent's recent ledger activity.
---

# AgentLedgerState

Defined in [`parrot.autonomous.ledger`](../summaries/mod:parrot.autonomous.ledger.md).

```python
class AgentLedgerState(BaseModel)
```

Read projection of an agent's recent ledger activity.

Consumed by ``/health`` and ``/status`` endpoints (FEAT-210).

Attributes:
    agent_id: The agent whose state this describes.
    last_activity: Timestamp of the most recent ledger entry for this agent.
    open_executions: Count of traces with an opening event but no closing event.
    closed_executions: Count of traces with both opening and closing events.
    total_events: Total number of ledger rows for this agent.
