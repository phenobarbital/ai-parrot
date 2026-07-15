---
type: Wiki Entity
title: AddOrganizationPositionInput
id: class:parrot_tools.interfaces.gigsmart.models.position.AddOrganizationPositionInput
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Input for the ``addOrganizationPosition`` mutation.
---

# AddOrganizationPositionInput

Defined in [`parrot_tools.interfaces.gigsmart.models.position`](../summaries/mod:parrot_tools.interfaces.gigsmart.models.position.md).

```python
class AddOrganizationPositionInput(BaseModel)
```

Input for the ``addOrganizationPosition`` mutation.

All instances are immutable (``frozen=True``) for safe passing as
GraphQL variables.

Args:
    organization_id: Target organisation ID.
    name: Position display name.
    description: Detailed position description.
    pay_rate: ISO-4217 money scalar, e.g. ``"20.00"``.
    pay_schedule: Payment schedule type.
    gig_category_id: Category ID from the GigSmart category taxonomy.
    gig_position_id: Optional position template ID.
    state: Initial position state.
    accepts_tips: Whether tips are accepted for this position.
    requires_vehicle: Whether workers need a vehicle.
    estimated_mileage: Estimated driving mileage per shift.
