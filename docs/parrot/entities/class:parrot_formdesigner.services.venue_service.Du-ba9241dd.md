---
type: Wiki Entity
title: DuplicateVenueError
id: class:parrot_formdesigner.services.venue_service.DuplicateVenueError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Raised when a UNIQUE constraint on a site/location is violated.
---

# DuplicateVenueError

Defined in [`parrot_formdesigner.services.venue_service`](../summaries/mod:parrot_formdesigner.services.venue_service.md).

```python
class DuplicateVenueError(Exception)
```

Raised when a UNIQUE constraint on a site/location is violated.

Attributes:
    kind: ``"site"`` or ``"location"``.
    name: The duplicate name.
