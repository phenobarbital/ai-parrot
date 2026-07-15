---
type: Wiki Entity
title: JobPostingType
id: class:parrot_tools.interfaces.workday.handlers.job_postings.JobPostingType
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Handler for the Workday Get_Job_Postings operation.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# JobPostingType

Defined in [`parrot_tools.interfaces.workday.handlers.job_postings`](../summaries/mod:parrot_tools.interfaces.workday.handlers.job_postings.md).

```python
class JobPostingType(WorkdayTypeBase)
```

Handler for the Workday Get_Job_Postings operation.

## Methods

- `async def execute(self, **kwargs) -> pd.DataFrame` — Execute the Get_Job_Postings operation and return a pandas DataFrame.
