---
type: Wiki Entity
title: JobPostingSite
id: class:parrot_tools.interfaces.workday.models.job_posting_site.JobPostingSite
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Job Posting Site model based on Workday Get_Job_Posting_Sites API.
---

# JobPostingSite

Defined in [`parrot_tools.interfaces.workday.models.job_posting_site`](../summaries/mod:parrot_tools.interfaces.workday.models.job_posting_site.md).

```python
class JobPostingSite(BaseModel)
```

Job Posting Site model based on Workday Get_Job_Posting_Sites API.

## Methods

- `def parse_boolean_fields(cls, v)` — Convert boolean-like values to proper booleans.
- `def parse_list_fields(cls, v)` — Ensure list fields are properly parsed.
- `def parse_integer_fields(cls, v)` — Convert integer-like values to proper integers.
- `def parse_date_fields(cls, v)` — Convert date objects to string format.
