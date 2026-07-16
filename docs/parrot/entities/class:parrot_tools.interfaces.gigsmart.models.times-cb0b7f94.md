---
type: Wiki Entity
title: ApproveEngagementTimesheetInput
id: class:parrot_tools.interfaces.gigsmart.models.timesheet.ApproveEngagementTimesheetInput
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Input for the ``approveEngagementTimesheet`` mutation.
---

# ApproveEngagementTimesheetInput

Defined in [`parrot_tools.interfaces.gigsmart.models.timesheet`](../summaries/mod:parrot_tools.interfaces.gigsmart.models.timesheet.md).

```python
class ApproveEngagementTimesheetInput(BaseModel)
```

Input for the ``approveEngagementTimesheet`` mutation.

Args:
    timesheet_id: Opaque ID of the timesheet to approve.
    mutation_lock: Optional optimistic-concurrency lock token.
