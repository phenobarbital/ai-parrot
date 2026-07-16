---
type: Wiki Entity
title: TransitionEngagementInput
id: class:parrot_tools.interfaces.gigsmart.models.engagement.TransitionEngagementInput
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Input for the single ``transitionEngagement`` mutation.
---

# TransitionEngagementInput

Defined in [`parrot_tools.interfaces.gigsmart.models.engagement`](../summaries/mod:parrot_tools.interfaces.gigsmart.models.engagement.md).

```python
class TransitionEngagementInput(BaseModel)
```

Input for the single ``transitionEngagement`` mutation.

This is the **only** mutation for ALL engagement state changes.
There are no separate hire, accept, cancel, or end mutations.

Args:
    engagement_id: Opaque ID of the engagement to transition.
    action: EngagementStateAction value (e.g. ``"HIRE"``, ``"CANCEL"``,
        ``"START"``, ``"END"``, ``"APPROVE_TIMESHEET"``).
    cancel_conflicting_engagements: Whether to cancel conflicting active
        engagements when applying this transition.
