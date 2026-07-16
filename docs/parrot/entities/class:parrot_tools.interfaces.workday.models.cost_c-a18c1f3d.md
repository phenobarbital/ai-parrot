---
type: Wiki Entity
title: CostCenter
id: class:parrot_tools.interfaces.workday.models.cost_center.CostCenter
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Complete cost center model based on Workday Get_Cost_Centers API documentation.
---

# CostCenter

Defined in [`parrot_tools.interfaces.workday.models.cost_center`](../summaries/mod:parrot_tools.interfaces.workday.models.cost_center.md).

```python
class CostCenter(BaseModel)
```

Complete cost center model based on Workday Get_Cost_Centers API documentation.

## Methods

- `def parse_boolean_fields(cls, v)` — Convert boolean-like values to proper booleans.
- `def parse_list_fields(cls, v)` — Ensure list fields are properly parsed.
- `def parse_date_fields(cls, v)` — Convert date objects to string format.
