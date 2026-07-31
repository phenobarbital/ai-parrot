---
type: Wiki Entity
title: JobPostingSiteType
id: class:parrot_tools.interfaces.workday.handlers.job_posting_sites.JobPostingSiteType
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handler for the Workday Get_Job_Posting_Sites operation.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# JobPostingSiteType

Defined in [`parrot_tools.interfaces.workday.handlers.job_posting_sites`](../summaries/mod:parrot_tools.interfaces.workday.handlers.job_po-817325f3.md).

```python
class JobPostingSiteType(WorkdayTypeBase)
```

Handler for the Workday Get_Job_Posting_Sites operation.

## Methods

- `async def execute(self, **kwargs) -> pd.DataFrame` — Execute the Get_Job_Posting_Sites operation and return a pandas DataFrame.
