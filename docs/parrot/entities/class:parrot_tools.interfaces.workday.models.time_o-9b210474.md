---
type: Wiki Entity
title: TimeOffBalance
id: class:parrot_tools.interfaces.workday.models.time_off_balance.TimeOffBalance
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic model for a Workday Time Off Plan Balance record.
---

# TimeOffBalance

Defined in [`parrot_tools.interfaces.workday.models.time_off_balance`](../summaries/mod:parrot_tools.interfaces.workday.models.time_off_balance.md).

```python
class TimeOffBalance(BaseModel)
```

Pydantic model for a Workday Time Off Plan Balance record.
Represents the CURRENT balance information for a worker's time off plan.

Note: This model only includes fields actually returned by the
Get_Time_Off_Plan_Balances API operation per the v45.0 documentation.
