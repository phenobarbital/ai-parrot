---
type: Wiki Entity
title: HitlTierAdvancedEvent
id: class:parrot.human.events.HitlTierAdvancedEvent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Emitted when the escalation cursor moves from one tier to another.
---

# HitlTierAdvancedEvent

Defined in [`parrot.human.events`](../summaries/mod:parrot.human.events.md).

```python
class HitlTierAdvancedEvent(BaseModel)
```

Emitted when the escalation cursor moves from one tier to another.

Attributes:
    interaction_id: UUID of the interaction being escalated.
    policy_id: Identifier of the escalation policy in use.
    from_level: The tier level being left.
    to_level: The tier level being entered.
    cause: Why the advance happened — ``"timeout"``, ``"reject"``,
        ``"business_hours_off"``, or ``"action_failed"``.
    timestamp: UTC datetime of the event.
