---
type: Wiki Summary
title: parrot_tools.interfaces.workday.handlers.time_off_request
id: mod:parrot_tools.interfaces.workday.handlers.time_off_request
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: RequestTimeOffType — handler for Request_Time_Off.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.time_off_request.RequestTimeOffType
  rel: defines
- concept: mod:parrot_tools.interfaces.workday.handlers.base
  rel: references
---

# `parrot_tools.interfaces.workday.handlers.time_off_request`

RequestTimeOffType — handler for Request_Time_Off.

Builds the SOAP request body for submitting a time-off request to Workday
Absence Management and parses the acknowledgment into a one-row status
DataFrame.

SOAP body shapes (Absence Management WSDL, Request_Time_Off operation):
- Time_Off_Request_Data.Worker_Reference        → Employee_ID reference
- Time_Off_Request_Data.Time_Off_Request_Line_Data[] →
    Time_Off_Type_Reference, Start_Date, End_Date, Daily_Quantity
- Optional Comment field at the request level.

Acknowledgment:
- Request_Time_Off_Response → contains the submitted request WID/ID.
- zeep raises a Validation_Fault/Processing_Fault on SOAP errors before this
  point, so arriving here means the submission was accepted.

## Classes

- **`RequestTimeOffType(WorkdayWriteTypeBase)`** — Handler for ``Request_Time_Off`` (Absence Management write op).
