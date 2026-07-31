---
type: Wiki Entity
title: JobPosting
id: class:parrot_tools.interfaces.workday.models.job_posting.JobPosting
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Job Posting model based on Workday Get_Job_Postings API.
---

# JobPosting

Defined in [`parrot_tools.interfaces.workday.models.job_posting`](../summaries/mod:parrot_tools.interfaces.workday.models.job_posting.md).

```python
class JobPosting(BaseModel)
```

Job Posting model based on Workday Get_Job_Postings API.

## Methods

- `def parse_boolean_fields(cls, v)` — Convert boolean-like values to proper booleans.
- `def parse_list_fields(cls, v)` — Ensure list fields are properly parsed.
- `def parse_integer_fields(cls, v)` — Convert integer-like values to proper integers.
- `def parse_numeric_fields(cls, v)` — Convert numeric-like values to proper numbers (int or float).
- `def parse_date_fields(cls, v)` — Convert date objects to string format.
