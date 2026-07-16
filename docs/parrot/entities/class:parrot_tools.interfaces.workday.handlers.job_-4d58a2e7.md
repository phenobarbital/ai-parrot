---
type: Wiki Entity
title: JobRequisitionType
id: class:parrot_tools.interfaces.workday.handlers.job_requisitions.JobRequisitionType
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handler for the Workday Get_Job_Requisitions operation.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# JobRequisitionType

Defined in [`parrot_tools.interfaces.workday.handlers.job_requisitions`](../summaries/mod:parrot_tools.interfaces.workday.handlers.job_re-9a20de79.md).

```python
class JobRequisitionType(WorkdayTypeBase)
```

Handler for the Workday Get_Job_Requisitions operation.

## Methods

- `async def execute(self, **kwargs) -> pd.DataFrame` — Execute the Get_Job_Requisitions operation and return a pandas DataFrame.
