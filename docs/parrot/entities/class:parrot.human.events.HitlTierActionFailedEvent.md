---
type: Wiki Entity
title: HitlTierActionFailedEvent
id: class:parrot.human.events.HitlTierActionFailedEvent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Emitted when an action raises an exception or returns ``error=True``.
---

# HitlTierActionFailedEvent

Defined in [`parrot.human.events`](../summaries/mod:parrot.human.events.md).

```python
class HitlTierActionFailedEvent(BaseModel)
```

Emitted when an action raises an exception or returns ``error=True``.

Attributes:
    interaction_id: UUID of the interaction.
    policy_id: Escalation policy identifier.
    tier_level: Tier level on which the action failed.
    kind: The action kind that failed.
    reason: Human-readable failure description.
    timestamp: UTC datetime of the event.
