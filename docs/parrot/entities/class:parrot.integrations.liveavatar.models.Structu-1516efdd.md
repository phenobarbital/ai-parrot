---
type: Wiki Entity
title: StructuredOutputMessage
id: class:parrot.integrations.liveavatar.models.StructuredOutputMessage
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Output-bridge contract for structured ai-parrot outputs (FEAT-249, relocated).
---

# StructuredOutputMessage

Defined in [`parrot.integrations.liveavatar.models`](../summaries/mod:parrot.integrations.liveavatar.models.md).

```python
class StructuredOutputMessage(BaseModel)
```

Output-bridge contract for structured ai-parrot outputs (FEAT-249, relocated).

Structured outputs (charts, data, canvas updates, tool calls) produced
during a voice or chat turn are published to the AgentChat UI WebSocket
channel keyed by :attr:`session_id` — the same conversation the avatar is
speaking.

Originally lived in ``livekit_agent/models.py``; relocated here (§3.4) so
Mode A/B/C structured-output delivery survives the Phase C deletion.

Attributes:
    type: Output kind, e.g. ``"chart"`` | ``"data"`` | ``"canvas"`` |
        ``"tool_call"``.
    session_id: Conversation id used as the WebSocket channel key.
    payload: Arbitrary structured payload the AgentChat UI renders.
    turn_id: Optional identifier of the turn that produced the output.
