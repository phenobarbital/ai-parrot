---
type: Wiki Entity
title: TimeRequestType
id: class:parrot_tools.interfaces.workday.handlers.time_requests.TimeRequestType
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handles Get_Time_Requests operation for Workday Time Tracking API.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# TimeRequestType

Defined in [`parrot_tools.interfaces.workday.handlers.time_requests`](../summaries/mod:parrot_tools.interfaces.workday.handlers.time_requests.md).

```python
class TimeRequestType(WorkdayTypeBase)
```

Handles Get_Time_Requests operation for Workday Time Tracking API.

## Methods

- `async def execute(self, **kwargs) -> pd.DataFrame` — Execute the Get_Time_Requests operation.
- `async def get_time_request_by_id(self, time_request_id: str) -> pd.DataFrame` — Get a specific time request by ID.
- `async def get_time_requests_by_worker(self, worker_id: str, start_date: Optional[date]=None, end_date: Optional[date]=None) -> pd.DataFrame` — Get time requests for a specific worker within an optional date range.
- `async def get_time_requests_by_organization(self, supervisory_organization_id: str, start_date: Optional[date]=None, end_date: Optional[date]=None) -> pd.DataFrame` — Get time requests for a specific organization within an optional date range.
- `async def get_time_requests_by_date_range(self, start_date: date, end_date: date) -> pd.DataFrame` — Get all time requests within a date range.
- `def safe_serialize(self, df: pd.DataFrame) -> pd.DataFrame` — Safely serialize the DataFrame for JSON output.
