---
type: Wiki Summary
title: parrot_tools.interfaces.workday.models.clock_event
id: mod:parrot_tools.interfaces.workday.models.clock_event
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Clock-event Pydantic models for Workday Time Tracking write operations.
relates_to:
- concept: class:parrot_tools.interfaces.workday.models.clock_event.ClockEvent
  rel: defines
- concept: class:parrot_tools.interfaces.workday.models.clock_event.ClockEventResult
  rel: defines
- concept: class:parrot_tools.interfaces.workday.models.clock_event.ReportedTimeBlock
  rel: defines
---

# `parrot_tools.interfaces.workday.models.clock_event`

Clock-event Pydantic models for Workday Time Tracking write operations.

These are pure data models with no SOAP coupling.  They are used by the
write handlers (PutTimeClockEventsType, ImportTimeClockEventsType,
ImportReportedTimeBlocksType) and by the Workday component for input
validation before any SOAP call (G7).

## Classes

- **`ClockEvent(BaseModel)`** — One Time Clock Event for Put_Time_Clock_Events / Import_Time_Clock_Events.
- **`ReportedTimeBlock(BaseModel)`** — One reported time block for Import_Reported_Time_Blocks.
- **`ClockEventResult(BaseModel)`** — Per-row submission outcome echoed back into the flow (G6).
