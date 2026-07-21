---
type: Wiki Entity
title: Engagement
id: class:parrot_tools.interfaces.gigsmart.models.engagement.Engagement
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A GigSmart engagement resource linking a worker to a gig.
---

# Engagement

Defined in [`parrot_tools.interfaces.gigsmart.models.engagement`](../summaries/mod:parrot_tools.interfaces.gigsmart.models.engagement.md).

```python
class Engagement(BaseModel)
```

A GigSmart engagement resource linking a worker to a gig.

Args:
    id: Opaque prefixed engagement ID (e.g. ``"eng_0WjivXE8xbrgBuEkfpANQP"``).
    gig_id: ID of the parent gig.
    worker_display_name: Worker's display name (PII — may be scrubbed in logs).
    current_state: Dict containing at least ``{"name": "<EngagementStateName>"}``.
    applied_at: Timestamp when the worker applied.
    hired_at: Timestamp when the worker was hired.
