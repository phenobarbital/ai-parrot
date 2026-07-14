---
type: Wiki Summary
title: parrot_tools.interfaces.gigsmart.models.timesheet
id: mod:parrot_tools.interfaces.gigsmart.models.timesheet
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pydantic v2 models for GigSmart timesheets and disputes API surfaces.
relates_to:
- concept: class:parrot_tools.interfaces.gigsmart.models.timesheet.AddEngagementDisputeInput
  rel: defines
- concept: class:parrot_tools.interfaces.gigsmart.models.timesheet.ApproveEngagementTimesheetInput
  rel: defines
- concept: class:parrot_tools.interfaces.gigsmart.models.timesheet.EngagementTimesheet
  rel: defines
- concept: class:parrot_tools.interfaces.gigsmart.models.timesheet.RemoveEngagementTimesheetInput
  rel: defines
- concept: class:parrot_tools.interfaces.gigsmart.models.timesheet.SetEngagementDisputeApprovalInput
  rel: defines
---

# `parrot_tools.interfaces.gigsmart.models.timesheet`

Pydantic v2 models for GigSmart timesheets and disputes API surfaces.

Important: there is NO ``TimesheetState`` enum in the GigSmart schema.
Timesheet lifecycle is tracked via ``EngagementStateName``
(``PENDING_TIMESHEET_APPROVAL``, ``DISBURSED``) plus the ``is_approved``
boolean on :class:`EngagementTimesheet`.

## Classes

- **`EngagementTimesheet(BaseModel)`** — A GigSmart engagement timesheet record.
- **`ApproveEngagementTimesheetInput(BaseModel)`** — Input for the ``approveEngagementTimesheet`` mutation.
- **`RemoveEngagementTimesheetInput(BaseModel)`** — Input for the ``removeEngagementTimesheet`` mutation.
- **`AddEngagementDisputeInput(BaseModel)`** — Input for the ``addEngagementDispute`` mutation.
- **`SetEngagementDisputeApprovalInput(BaseModel)`** — Input for the ``setEngagementDisputeApproval`` mutation.
