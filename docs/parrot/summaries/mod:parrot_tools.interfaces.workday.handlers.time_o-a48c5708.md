---
type: Wiki Summary
title: parrot_tools.interfaces.workday.handlers.time_off_eligibility
id: mod:parrot_tools.interfaces.workday.handlers.time_off_eligibility
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: TimeOffEligibilityType — read handler for Get_Time_Off_Types.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.time_off_eligibility.TimeOffEligibilityType
  rel: defines
- concept: mod:parrot_tools.interfaces.workday.handlers.base
  rel: references
- concept: mod:parrot_tools.interfaces.workday.models.time_off_eligibility
  rel: references
---

# `parrot_tools.interfaces.workday.handlers.time_off_eligibility`

TimeOffEligibilityType — read handler for Get_Time_Off_Types.

Fetches the list of time-off types a worker is eligible to request from
Workday Absence Management and returns them as a list of
``TimeOffEligibility`` Pydantic models via the standard handler contract.

## Classes

- **`TimeOffEligibilityType(WorkdayTypeBase)`** — Handler for ``Get_Time_Off_Types`` (Absence Management read op).
