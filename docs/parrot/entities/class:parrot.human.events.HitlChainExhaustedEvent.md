---
type: Wiki Entity
title: HitlChainExhaustedEvent
id: class:parrot.human.events.HitlChainExhaustedEvent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Emitted when the escalation chain terminates after exhausting all tiers.
---

# HitlChainExhaustedEvent

Defined in [`parrot.human.events`](../summaries/mod:parrot.human.events.md).

```python
class HitlChainExhaustedEvent(BaseModel)
```

Emitted when the escalation chain terminates after exhausting all tiers.

Attributes:
    interaction_id: UUID of the interaction.
    policy_id: Escalation policy identifier.
    timestamp: UTC datetime of the event.
