---
type: Wiki Summary
title: parrot_tools.interfaces.workday.models.custom_punch_field_report
id: mod:parrot_tools.interfaces.workday.models.custom_punch_field_report
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pydantic models for Workday Custom Punch - Field Report.
relates_to:
- concept: class:parrot_tools.interfaces.workday.models.custom_punch_field_report.CustomPunchFieldReportEntry
  rel: defines
- concept: class:parrot_tools.interfaces.workday.models.custom_punch_field_report.WorkerGroup
  rel: defines
---

# `parrot_tools.interfaces.workday.models.custom_punch_field_report`

Pydantic models for Workday Custom Punch - Field Report.

This report provides detailed punch/time entry information with calculated fields,
wages, and override information.

## Classes

- **`WorkerGroup(BaseModel)`** — Worker group information containing employee details.
- **`CustomPunchFieldReportEntry(BaseModel)`** — Model for a single entry in the Custom Punch - Field Report.
