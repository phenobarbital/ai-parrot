---
type: Wiki Summary
title: parrot_tools.interfaces.workday.handlers.import_time_clock_events
id: mod:parrot_tools.interfaces.workday.handlers.import_time_clock_events
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: ImportTimeClockEventsType — handler for Import_Time_Clock_Events.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.import_time_clock_events.ImportTimeClockEventsType
  rel: defines
- concept: mod:parrot_tools.interfaces.workday.handlers.base
  rel: references
- concept: mod:parrot_tools.interfaces.workday.models.clock_event
  rel: references
---

# `parrot_tools.interfaces.workday.handlers.import_time_clock_events`

ImportTimeClockEventsType — handler for Import_Time_Clock_Events.

Builds the SOAP request body from a list of ClockEvent models, invokes
``self.service.call_operation(operation="Import_Time_Clock_Events", ...)``,
and parses the Put_Import_Process_ResponseType into a per-row status DataFrame.

SOAP body shapes: same field types as Put (clock event data), plus optional
batch_id.

Acknowledgment (Import_Time_Clock_Events_Response → Put_Import_Process_ResponseType):
  { "Import_Process_Reference": <ref>, "Header_Instance_Reference": <ref> }
  This is an ASYNC background process — we surface the reference but do NOT poll
  for terminal status (Non-Goal per spec §1).

## Classes

- **`ImportTimeClockEventsType(WorkdayWriteTypeBase)`** — Handler for ``Import_Time_Clock_Events`` (batch async import).
