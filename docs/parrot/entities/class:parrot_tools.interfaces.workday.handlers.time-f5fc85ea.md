---
type: Wiki Entity
title: TimeOffEligibilityType
id: class:parrot_tools.interfaces.workday.handlers.time_off_eligibility.TimeOffEligibilityType
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handler for ``Get_Time_Off_Types`` (Absence Management read op).
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# TimeOffEligibilityType

Defined in [`parrot_tools.interfaces.workday.handlers.time_off_eligibility`](../summaries/mod:parrot_tools.interfaces.workday.handlers.time_o-a48c5708.md).

```python
class TimeOffEligibilityType(WorkdayTypeBase)
```

Handler for ``Get_Time_Off_Types`` (Absence Management read op).

## Methods

- `async def execute(self, *, worker_id: str, **kwargs: Any) -> pd.DataFrame` — Fetch eligible time-off types for a worker.
