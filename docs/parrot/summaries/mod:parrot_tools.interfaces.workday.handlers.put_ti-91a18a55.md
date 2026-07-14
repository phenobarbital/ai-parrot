---
type: Wiki Summary
title: parrot_tools.interfaces.workday.handlers.put_time_clock_events
id: mod:parrot_tools.interfaces.workday.handlers.put_time_clock_events
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: PutTimeClockEventsType — handler for Put_Time_Clock_Events.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.put_time_clock_events.PutTimeClockEventsType
  rel: defines
- concept: mod:parrot_tools.interfaces.workday.handlers.base
  rel: references
- concept: mod:parrot_tools.interfaces.workday.models.clock_event
  rel: references
---

# `parrot_tools.interfaces.workday.handlers.put_time_clock_events`

PutTimeClockEventsType — handler for Put_Time_Clock_Events.

Builds the SOAP request body from a list of ClockEvent models, invokes
``self.service.call_operation(operation="Put_Time_Clock_Events", ...)``,
and parses the acknowledgment into a per-row ClockEventResult DataFrame.

SOAP body shapes (verified in timetracking_custom_44_2.wsdl + Workday WWS v46.1):
- Time_Clock_Event_Data repeats per event (maxOccurs unbounded).
- Clock_Event_Type_Reference  → {"ID": {"type": "Clock_Event_Type", "_value_1": "In|Break|Meal|Out"}}
- Time_Zone_Reference          → {"ID": {"type": "Time_Zone_ID", "_value_1": <tz>}}
- Employee_ID / Position_ID / Time_Clock_Event_ID / Time_Entry_Code → plain xsd:string.
- Time_Clock_Event_Date_Time   → xsd:dateTime (isoformat).

Acknowledgment:
- Put_Time_Clock_Events_Response → {"Response_Text": str} ONLY (no per-event WID, any version).
- Put is ATOMIC: a Validation_Fault/Processing_Fault marks ALL rows failed.

## Classes

- **`PutTimeClockEventsType(WorkdayWriteTypeBase)`** — Handler for ``Put_Time_Clock_Events`` (real-time clock-event submission).
