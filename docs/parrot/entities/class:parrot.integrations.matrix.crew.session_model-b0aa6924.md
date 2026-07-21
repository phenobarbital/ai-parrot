---
type: Wiki Entity
title: AgentRoundResult
id: class:parrot.integrations.matrix.crew.session_models.AgentRoundResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Result from one agent for one investigation round.
---

# AgentRoundResult

Defined in [`parrot.integrations.matrix.crew.session_models`](../summaries/mod:parrot.integrations.matrix.crew.session_models.md).

```python
class AgentRoundResult(BaseModel)
```

Result from one agent for one investigation round.

Stores the text response and the Matrix event ID of the message
posted to the room (used for ``m.in_reply_to`` threading in
cross-pollination rounds).

Attributes:
    agent_name: Internal agent name (key in crew config).
    display_name: Human-readable agent display name.
    mxid: Full Matrix user ID of the virtual agent.
    round_number: Round index (0 = investigation, 1..N = cross-pollination).
    result_text: Agent's response text.
    event_id: Matrix event ID of the posted message (for reply-to threading).
    timestamp: When the result was produced.
