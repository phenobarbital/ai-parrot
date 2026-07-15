---
type: Wiki Entity
title: OrganizationLocation
id: class:parrot_tools.interfaces.gigsmart.models.location.OrganizationLocation
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A location belonging to a GigSmart organisation.
---

# OrganizationLocation

Defined in [`parrot_tools.interfaces.gigsmart.models.location`](../summaries/mod:parrot_tools.interfaces.gigsmart.models.location.md).

```python
class OrganizationLocation(BaseModel)
```

A location belonging to a GigSmart organisation.

Args:
    id: Opaque prefixed location ID (e.g. ``"loc_..."``).
    name: Location display name.
    state: Location status/state string.
    latitude: Optional GPS latitude.
    longitude: Optional GPS longitude.
    created_at: Optional creation timestamp.
