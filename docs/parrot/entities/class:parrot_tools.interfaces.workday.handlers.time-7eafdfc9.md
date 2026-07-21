---
type: Wiki Entity
title: TimeOffBalanceType
id: class:parrot_tools.interfaces.workday.handlers.time_off_balances.TimeOffBalanceType
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handles Get_Time_Off_Plan_Balances operation for Workday Absence Management
  API.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# TimeOffBalanceType

Defined in [`parrot_tools.interfaces.workday.handlers.time_off_balances`](../summaries/mod:parrot_tools.interfaces.workday.handlers.time_o-da072657.md).

```python
class TimeOffBalanceType(WorkdayTypeBase)
```

Handles Get_Time_Off_Plan_Balances operation for Workday Absence Management API.

## Methods

- `async def execute(self, **kwargs) -> pd.DataFrame` — Execute the Get_Time_Off_Plan_Balances operation.
- `async def get_balances_by_worker(self, worker_id: str) -> pd.DataFrame` — Convenience method to get current time off balances for a specific worker.
- `async def get_balances_by_plan(self, time_off_plan_id: str) -> pd.DataFrame` — Convenience method to get current balances for a specific time off plan.
- `async def get_balances_by_organization(self, organization_id: str) -> pd.DataFrame` — Convenience method to get current balances for a specific organization.
