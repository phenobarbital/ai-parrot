---
type: Wiki Entity
title: ReportedTimeBlock
id: class:parrot_tools.interfaces.workday.models.clock_event.ReportedTimeBlock
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: One reported time block for Import_Reported_Time_Blocks.
---

# ReportedTimeBlock

Defined in [`parrot_tools.interfaces.workday.models.clock_event`](../summaries/mod:parrot_tools.interfaces.workday.models.clock_event.md).

```python
class ReportedTimeBlock(BaseModel)
```

One reported time block for Import_Reported_Time_Blocks.

Args:
    employee_id: Workday Employee_ID (required).
    position_id: Optional Position_ID.
    start_datetime: Block start date/time (required).
    end_datetime: Block end date/time (optional; ISO-8601 string accepted).
    time_entry_code: Optional Time_Entry_Code (plain string).
    reported_quantity: Optional duration/quantity of time.
    comment: Optional free-text comment.
