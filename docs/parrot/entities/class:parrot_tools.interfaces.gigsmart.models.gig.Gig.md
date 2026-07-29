---
type: Wiki Entity
title: Gig
id: class:parrot_tools.interfaces.gigsmart.models.gig.Gig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A GigSmart shift/gig resource.
---

# Gig

Defined in [`parrot_tools.interfaces.gigsmart.models.gig`](../summaries/mod:parrot_tools.interfaces.gigsmart.models.gig.md).

```python
class Gig(BaseModel)
```

A GigSmart shift/gig resource.

Args:
    id: Opaque prefixed gig ID (e.g. ``"gig_9ucAiJfkccqJKbnVytgviu"``).
    name: Optional auto-generated or human-assigned shift name.
    starts_at: Shift start time.
    ends_at: Shift end time.
    current_state: Dict containing at least ``{"name": "<GigStateName>"}``.
    slots_available: Number of open worker slots.
