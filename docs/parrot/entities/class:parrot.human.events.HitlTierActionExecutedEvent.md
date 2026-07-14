---
type: Wiki Entity
title: HitlTierActionExecutedEvent
id: class:parrot.human.events.HitlTierActionExecutedEvent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Emitted after a NOTIFY or TICKET action completes successfully.
---

# HitlTierActionExecutedEvent

Defined in [`parrot.human.events`](../summaries/mod:parrot.human.events.md).

```python
class HitlTierActionExecutedEvent(BaseModel)
```

Emitted after a NOTIFY or TICKET action completes successfully.

Attributes:
    interaction_id: UUID of the interaction.
    policy_id: Escalation policy identifier.
    tier_level: Tier level on which the action ran.
    kind: The action kind (e.g. ``"email"``, ``"zammad"``,
        ``"webhook"``), taken from ``action_metadata.get("kind")``.
    action_metadata: The raw result dict returned by the action
        backend (may contain message, ticket_id, url, etc.).
    timestamp: UTC datetime of the event.
