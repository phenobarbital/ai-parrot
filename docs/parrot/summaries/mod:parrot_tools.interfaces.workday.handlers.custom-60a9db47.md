---
type: Wiki Summary
title: parrot_tools.interfaces.workday.handlers.custom_punch_field_report
id: mod:parrot_tools.interfaces.workday.handlers.custom_punch_field_report
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Type handler for Workday Custom Punch - Field Report.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.custom_punch_field_report.CustomPunchFieldReportType
  rel: defines
- concept: mod:parrot_tools.interfaces.workday.handlers.base
  rel: references
- concept: mod:parrot_tools.interfaces.workday.models.custom_punch_field_report
  rel: references
- concept: mod:parrot_tools.interfaces.workday.parsers.custom_punch_field_report_parsers
  rel: references
---

# `parrot_tools.interfaces.workday.handlers.custom_punch_field_report`

Type handler for Workday Custom Punch - Field Report.

This handler executes the Custom Punch - Field Report via SOAP to get all fields
that might not be available in the REST API response.

## Classes

- **`CustomPunchFieldReportType(WorkdayTypeBase)`** — Handler for the Custom Punch - Field Report.
