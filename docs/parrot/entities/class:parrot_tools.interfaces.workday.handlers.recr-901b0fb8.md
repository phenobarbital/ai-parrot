---
type: Wiki Entity
title: RecruitingAgencyUsersType
id: class:parrot_tools.interfaces.workday.handlers.recruiting_agency_users.RecruitingAgencyUsersType
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handler for Get_Recruiting_Agency_Users operation from Recruiting API.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# RecruitingAgencyUsersType

Defined in [`parrot_tools.interfaces.workday.handlers.recruiting_agency_users`](../summaries/mod:parrot_tools.interfaces.workday.handlers.recrui-e66fd23b.md).

```python
class RecruitingAgencyUsersType(WorkdayTypeBase)
```

Handler for Get_Recruiting_Agency_Users operation from Recruiting API.

Uses serialize_object to dynamically map all fields from SOAP response without
requiring manual parsers. All fields are preserved in the DataFrame.

## Methods

- `async def execute(self, **kwargs) -> pd.DataFrame` — Execute Get_Recruiting_Agency_Users operation.
