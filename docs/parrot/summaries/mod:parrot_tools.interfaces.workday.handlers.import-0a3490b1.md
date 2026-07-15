---
type: Wiki Summary
title: parrot_tools.interfaces.workday.handlers.import_reported_time_blocks
id: mod:parrot_tools.interfaces.workday.handlers.import_reported_time_blocks
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: ImportReportedTimeBlocksType — handler for Import_Reported_Time_Blocks.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.import_reported_time_blocks.ImportReportedTimeBlocksType
  rel: defines
- concept: mod:parrot_tools.interfaces.workday.handlers.base
  rel: references
- concept: mod:parrot_tools.interfaces.workday.models.clock_event
  rel: references
---

# `parrot_tools.interfaces.workday.handlers.import_reported_time_blocks`

ImportReportedTimeBlocksType — handler for Import_Reported_Time_Blocks.

Builds the SOAP request body from a list of ReportedTimeBlock models, invokes
``self.service.call_operation(operation="Import_Reported_Time_Blocks", ...)``,
and parses the Put_Import_Process_ResponseType into a per-row status DataFrame.

Acknowledgment shape (same as Import_Time_Clock_Events):
  { "Import_Process_Reference": <ref>, "Header_Instance_Reference": <ref> }
  Async background process — reference surfaced but NOT polled (Non-Goal).

## Classes

- **`ImportReportedTimeBlocksType(WorkdayWriteTypeBase)`** — Handler for ``Import_Reported_Time_Blocks`` (batch async import).
