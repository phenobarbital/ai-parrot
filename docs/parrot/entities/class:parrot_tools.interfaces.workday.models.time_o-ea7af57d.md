---
type: Wiki Entity
title: TimeOffEligibility
id: class:parrot_tools.interfaces.workday.models.time_off_eligibility.TimeOffEligibility
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic model for a Workday eligible time-off type.
---

# TimeOffEligibility

Defined in [`parrot_tools.interfaces.workday.models.time_off_eligibility`](../summaries/mod:parrot_tools.interfaces.workday.models.time_off-72f6a0d8.md).

```python
class TimeOffEligibility(BaseModel)
```

Pydantic model for a Workday eligible time-off type.

Represents one time-off type a worker is eligible to request,
as returned by ``Get_Time_Off_Types`` (Absence Management WSDL).
