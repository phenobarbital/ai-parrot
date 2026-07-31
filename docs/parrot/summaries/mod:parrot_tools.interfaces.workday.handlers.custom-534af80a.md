---
type: Wiki Summary
title: parrot_tools.interfaces.workday.handlers.custom_punch_field_report_rest
id: mod:parrot_tools.interfaces.workday.handlers.custom_punch_field_report_rest
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: REST handler for the Custom Punch - Field Report (RaaS).
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.custom_punch_field_report_rest.CustomPunchFieldReportRestType
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.interfaces.http
  rel: references
- concept: mod:parrot_tools.interfaces.workday.handlers.base
  rel: references
- concept: mod:parrot_tools.interfaces.workday.models.custom_punch_field_report
  rel: references
- concept: mod:parrot_tools.interfaces.workday.parsers.custom_punch_field_report_parsers
  rel: references
---

# `parrot_tools.interfaces.workday.handlers.custom_punch_field_report_rest`

REST handler for the Custom Punch - Field Report (RaaS).

Uses the Workday customreport2 endpoint (basic auth) and returns a flattened
DataFrame from the XML response.

## Classes

- **`CustomPunchFieldReportRestType(WorkdayTypeBase)`** — Fetch the Custom Punch - Field Report via REST (customreport2).
