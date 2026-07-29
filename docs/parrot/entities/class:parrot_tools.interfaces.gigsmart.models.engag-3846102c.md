---
type: Wiki Entity
title: AddEngagementInput
id: class:parrot_tools.interfaces.gigsmart.models.engagement.AddEngagementInput
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Input for the ``addEngagement`` mutation.
---

# AddEngagementInput

Defined in [`parrot_tools.interfaces.gigsmart.models.engagement`](../summaries/mod:parrot_tools.interfaces.gigsmart.models.engagement.md).

```python
class AddEngagementInput(BaseModel)
```

Input for the ``addEngagement`` mutation.

All instances are immutable (``frozen=True``) for safe passing as
GraphQL variables.

Args:
    gig_id: The gig to create the engagement for.
    worker_id: Optional worker to target; omit to create an open offer.
    initial_state: Optional initial engagement state.
    pay_rate: ISO-4217 money scalar override for this engagement.
    pay_schedule: Payment schedule override.
    note: Optional note to the worker.
    cancel_conflicting_engagements: Whether to cancel conflicting active engagements.
