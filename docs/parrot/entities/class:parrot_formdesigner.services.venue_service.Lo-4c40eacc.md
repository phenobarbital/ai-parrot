---
type: Wiki Entity
title: LocationNotFoundError
id: class:parrot_formdesigner.services.venue_service.LocationNotFoundError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Raised when a location lookup returns no row.
---

# LocationNotFoundError

Defined in [`parrot_formdesigner.services.venue_service`](../summaries/mod:parrot_formdesigner.services.venue_service.md).

```python
class LocationNotFoundError(Exception)
```

Raised when a location lookup returns no row.

Attributes:
    location_id: The missing location identifier.
