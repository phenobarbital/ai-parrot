---
type: Wiki Entity
title: RemoveEngagementTimesheetInput
id: class:parrot_tools.interfaces.gigsmart.models.timesheet.RemoveEngagementTimesheetInput
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Input for the ``removeEngagementTimesheet`` mutation.
---

# RemoveEngagementTimesheetInput

Defined in [`parrot_tools.interfaces.gigsmart.models.timesheet`](../summaries/mod:parrot_tools.interfaces.gigsmart.models.timesheet.md).

```python
class RemoveEngagementTimesheetInput(BaseModel)
```

Input for the ``removeEngagementTimesheet`` mutation.

This rejects the timesheet and allows the worker to resubmit.
It does NOT delete the timesheet record.

Args:
    timesheet_id: Opaque ID of the timesheet to reject/send back.
