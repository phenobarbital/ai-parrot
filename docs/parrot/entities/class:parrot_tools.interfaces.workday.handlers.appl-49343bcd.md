---
type: Wiki Entity
title: ApplicantType
id: class:parrot_tools.interfaces.workday.handlers.applicants.ApplicantType
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handler for the Workday Get_Applicants operation from Recruiting API.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# ApplicantType

Defined in [`parrot_tools.interfaces.workday.handlers.applicants`](../summaries/mod:parrot_tools.interfaces.workday.handlers.applicants.md).

```python
class ApplicantType(WorkdayTypeBase)
```

Handler for the Workday Get_Applicants operation from Recruiting API.

Based on Workday Recruiting API v44.2:
https://community.workday.com/sites/default/files/file-hosting/productionapi/Recruiting/v44.2/Get_Applicants.html

Returns information for pre-hires/applicants. This is used to get candidates
that have not been converted to Workers yet (pre-hires with future hire dates).

## Methods

- `async def execute(self, **kwargs) -> pd.DataFrame` — Execute the Get_Applicants operation and return a pandas DataFrame.
