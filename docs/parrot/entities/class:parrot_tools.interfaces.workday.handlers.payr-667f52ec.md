---
type: Wiki Entity
title: PayrollResultsType
id: class:parrot_tools.interfaces.workday.handlers.payroll.PayrollResultsType
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Get_Payroll_Results — historical / off-cycle payroll results for a worker.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# PayrollResultsType

Defined in [`parrot_tools.interfaces.workday.handlers.payroll`](../summaries/mod:parrot_tools.interfaces.workday.handlers.payroll.md).

```python
class PayrollResultsType(WorkdayTypeBase)
```

Get_Payroll_Results — historical / off-cycle payroll results for a worker.

## Methods

- `async def execute(self, *, worker_id: str, start_date: Optional[str]=None, end_date: Optional[str]=None, include_details: bool=False, **_kwargs: Any) -> List[Dict[str, Any]]`
