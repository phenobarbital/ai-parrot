---
type: Wiki Entity
title: EngagementTimesheet
id: class:parrot_tools.interfaces.gigsmart.models.timesheet.EngagementTimesheet
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A GigSmart engagement timesheet record.
---

# EngagementTimesheet

Defined in [`parrot_tools.interfaces.gigsmart.models.timesheet`](../summaries/mod:parrot_tools.interfaces.gigsmart.models.timesheet.md).

```python
class EngagementTimesheet(BaseModel)
```

A GigSmart engagement timesheet record.

Variants: ADMIN, FINAL, LATEST, REQUESTER, SYSTEM, WORKER.
Payment styles: CALCULATED, FIXED_AMOUNT, FIXED_HOURS.

Args:
    id: Opaque prefixed timesheet ID (e.g. ``"engts_9fesLHHFy0By8MC6FvbYiv"``).
    engagement_id: Parent engagement ID.
    is_approved: True when the requester has approved this timesheet.
    variant: Which timesheet variant this record represents.
    payment_style: How payment is calculated.
