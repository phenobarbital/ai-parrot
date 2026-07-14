---
type: Wiki Entity
title: AddOrganizationLocationInput
id: class:parrot_tools.interfaces.gigsmart.models.location.AddOrganizationLocationInput
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Input for the ``addOrganizationLocation`` mutation.
---

# AddOrganizationLocationInput

Defined in [`parrot_tools.interfaces.gigsmart.models.location`](../summaries/mod:parrot_tools.interfaces.gigsmart.models.location.md).

```python
class AddOrganizationLocationInput(BaseModel)
```

Input for the ``addOrganizationLocation`` mutation.

All instances are immutable (``frozen=True``) for safe passing as
GraphQL variables.

Args:
    organization_id: The organisation to add the location to.
    name: Location name (1–120 characters).
    place_id: Optional Google/geocoder place ID to resolve the address.
    address: Raw address string, used when place_id is not available.
    primary_contact_id: Optional ID of the requester contact for this location.
    payment_method_id: Optional payment method to associate with the location.
    arrival_instructions: Instructions for workers arriving at the location.
    location_instructions: Additional location-specific instructions.
