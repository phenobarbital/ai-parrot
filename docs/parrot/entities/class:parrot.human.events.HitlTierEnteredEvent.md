---
type: Wiki Entity
title: HitlTierEnteredEvent
id: class:parrot.human.events.HitlTierEnteredEvent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Emitted when the escalation cursor enters a tier for the first time.
---

# HitlTierEnteredEvent

Defined in [`parrot.human.events`](../summaries/mod:parrot.human.events.md).

```python
class HitlTierEnteredEvent(BaseModel)
```

Emitted when the escalation cursor enters a tier for the first time.

Attributes:
    interaction_id: UUID of the interaction being escalated.
    policy_id: Identifier of the escalation policy in use.
    tier_level: The tier level being entered (1-based).
    cause: What triggered the entry — ``"initial"`` when the manager
        first resolves the policy; ``"timeout"``, ``"reject"``,
        ``"business_hours_off"``, or ``"action_failed"`` on
        subsequent advances.
    timestamp: UTC datetime of the event.
