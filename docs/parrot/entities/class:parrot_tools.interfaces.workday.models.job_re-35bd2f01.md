---
type: Wiki Entity
title: JobRequisition
id: class:parrot_tools.interfaces.workday.models.job_requisition.JobRequisition
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Complete job requisition model based on Workday Get_Job_Requisitions API
  documentation.
---

# JobRequisition

Defined in [`parrot_tools.interfaces.workday.models.job_requisition`](../summaries/mod:parrot_tools.interfaces.workday.models.job_requisition.md).

```python
class JobRequisition(BaseModel)
```

Complete job requisition model based on Workday Get_Job_Requisitions API documentation.

## Methods

- `def parse_boolean_fields(cls, v)` — Convert boolean-like values to proper booleans.
- `def parse_list_fields(cls, v)` — Ensure list fields are properly parsed.
- `def parse_integer_fields(cls, v)` — Convert integer-like values to proper integers.
- `def parse_numeric_fields(cls, v)` — Convert numeric-like values to proper numbers (int or float).
- `def parse_date_fields(cls, v)` — Convert date objects to string format.
