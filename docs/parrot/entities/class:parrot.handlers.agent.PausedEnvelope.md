---
type: Wiki Entity
title: PausedEnvelope
id: class:parrot.handlers.agent.PausedEnvelope
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: HTTP-200 structured reply returned by AgentTalk when a SUSPEND tool raises
---

# PausedEnvelope

Defined in [`parrot.handlers.agent`](../summaries/mod:parrot.handlers.agent.md).

```python
class PausedEnvelope(BaseModel)
```

HTTP-200 structured reply returned by AgentTalk when a SUSPEND tool raises
HumanInteractionInterrupt.

Modelled on AuthRequiredEnvelope — the frontend detects ``status == "paused"``
and renders the appropriate HITL widget for the interaction type.

Attributes:
    status: Discriminator literal — always ``"paused"``.
    turn_id: Correlation ID wrapping interaction_id (shared with resume path).
    interaction_id: UUID of the pending HumanInteraction in Redis.
    interaction_type: Interaction type string (e.g. ``"single_choice"``).
    question: The question posed to the human.
    context: Optional short background shown above the question.
    options: For choice-type interactions — list of option dicts.
    form_schema: For form-type interactions — JSON Schema dict.
    default_response: Default value if the human does not respond in time.
    deadline: ISO-8601 absolute expiry derived from the interaction TTL.
    source_agent: Name of the agent that raised the interrupt.
