---
type: Wiki Entity
title: PostShiftInput
id: class:parrot_tools.interfaces.gigsmart.models.gig.PostShiftInput
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Input for the ``postShift`` mutation.
---

# PostShiftInput

Defined in [`parrot_tools.interfaces.gigsmart.models.gig`](../summaries/mod:parrot_tools.interfaces.gigsmart.models.gig.md).

```python
class PostShiftInput(BaseModel)
```

Input for the ``postShift`` mutation.

All instances are immutable (``frozen=True``) for safe passing as
GraphQL variables.

Args:
    organization_id: The organisation that will host the shift.
    organization_position_id: Position template for the shift.
    organization_location_id: Physical location for the shift.
    starts_at: Shift start time (ISO-8601 datetime with timezone).
    ends_at: Shift end time (ISO-8601 datetime with timezone).
    pay_rate: ISO-4217 money scalar override (defaults to position rate).
    slots_available: Number of worker slots (minimum 1).
    description: Optional shift-specific instructions (max 5 000 chars).
    requester_id: Optional requester who manages this shift.
