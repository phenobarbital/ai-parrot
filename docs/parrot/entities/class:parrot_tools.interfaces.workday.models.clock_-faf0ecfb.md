---
type: Wiki Entity
title: ClockEvent
id: class:parrot_tools.interfaces.workday.models.clock_event.ClockEvent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: One Time Clock Event for Put_Time_Clock_Events / Import_Time_Clock_Events.
---

# ClockEvent

Defined in [`parrot_tools.interfaces.workday.models.clock_event`](../summaries/mod:parrot_tools.interfaces.workday.models.clock_event.md).

```python
class ClockEvent(BaseModel)
```

One Time Clock Event for Put_Time_Clock_Events / Import_Time_Clock_Events.

Field names mirror the Workday Time Tracking operation; all references
are resolved to ID-typed SOAP structures inside the handler.

Args:
    employee_id: Workday Employee_ID (required, plain xsd:string).
    event_datetime: Time_Clock_Event_Date_Time (required, xsd:dateTime).
    clock_event_type: Clock_Event_Type_Reference value — one of
        ``In``, ``Break``, ``Meal``, ``Out`` (required).
    time_clock_event_id: CLIENT-assigned Time_Clock_Event_ID.  Leave
        ``None`` to let Workday auto-generate.  This is the per-event
        identifier; Workday returns NO WID in the Put response (v46.1).
    position_id: Optional Position_ID (plain xsd:string).
    time_zone: Optional Time_Zone_Reference value (``type="Time_Zone_ID"``).
    time_entry_code: Optional Time_Entry_Code (plain xsd:string, NOT a
        reference wrapper).
    auto_submit: Whether to auto-submit for approval (default ``False``).
    comment: Optional free-text comment.
