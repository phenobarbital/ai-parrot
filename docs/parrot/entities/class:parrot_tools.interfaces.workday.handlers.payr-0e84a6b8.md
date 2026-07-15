---
type: Wiki Entity
title: CompanyPaymentDatesType
id: class:parrot_tools.interfaces.workday.handlers.payroll.CompanyPaymentDatesType
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Get_Company_Payment_Dates — company payment dates in a window.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# CompanyPaymentDatesType

Defined in [`parrot_tools.interfaces.workday.handlers.payroll`](../summaries/mod:parrot_tools.interfaces.workday.handlers.payroll.md).

```python
class CompanyPaymentDatesType(WorkdayTypeBase)
```

Get_Company_Payment_Dates — company payment dates in a window.

## Methods

- `async def execute(self, *, start_date: str, end_date: str, pay_group_id: Optional[str]=None, **_kwargs: Any) -> List[Dict[str, Any]]`
