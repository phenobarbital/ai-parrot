---
type: Wiki Entity
title: PayrollBalancesType
id: class:parrot_tools.interfaces.workday.handlers.payroll.PayrollBalancesType
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Get_Payroll_Balances — payroll balances for a worker.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# PayrollBalancesType

Defined in [`parrot_tools.interfaces.workday.handlers.payroll`](../summaries/mod:parrot_tools.interfaces.workday.handlers.payroll.md).

```python
class PayrollBalancesType(WorkdayTypeBase)
```

Get_Payroll_Balances — payroll balances for a worker.

## Methods

- `async def execute(self, *, worker_id: str, start_date: Optional[str]=None, end_date: Optional[str]=None, pay_component_group_ids: Optional[List[str]]=None, **_kwargs: Any) -> Dict[str, Any]`
