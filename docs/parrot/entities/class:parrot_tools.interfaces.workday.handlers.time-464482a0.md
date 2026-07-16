---
type: Wiki Entity
title: RequestTimeOffType
id: class:parrot_tools.interfaces.workday.handlers.time_off_request.RequestTimeOffType
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handler for ``Request_Time_Off`` (Absence Management write op).
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayWriteTypeBase
  rel: extends
---

# RequestTimeOffType

Defined in [`parrot_tools.interfaces.workday.handlers.time_off_request`](../summaries/mod:parrot_tools.interfaces.workday.handlers.time_o-c8218c4e.md).

```python
class RequestTimeOffType(WorkdayWriteTypeBase)
```

Handler for ``Request_Time_Off`` (Absence Management write op).

## Methods

- `def build_request(self, worker_id: str, start_date: str, end_date: str, time_off_type: str, daily_quantity: float=8.0, comment: Optional[str]=None, **kwargs: Any) -> dict` — Build the Request_Time_Off SOAP body.
- `def parse_ack(self, raw: Any) -> pd.DataFrame` — Parse Request_Time_Off_Response into a one-row status DataFrame.
