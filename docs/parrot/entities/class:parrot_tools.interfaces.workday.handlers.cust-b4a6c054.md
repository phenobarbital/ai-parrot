---
type: Wiki Entity
title: CustomPunchFieldReportRestType
id: class:parrot_tools.interfaces.workday.handlers.custom_punch_field_report_rest.CustomPunchFieldReportRestType
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Fetch the Custom Punch - Field Report via REST (customreport2).
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# CustomPunchFieldReportRestType

Defined in [`parrot_tools.interfaces.workday.handlers.custom_punch_field_report_rest`](../summaries/mod:parrot_tools.interfaces.workday.handlers.custom-534af80a.md).

```python
class CustomPunchFieldReportRestType(WorkdayTypeBase)
```

Fetch the Custom Punch - Field Report via REST (customreport2).

Required params:
- start_date: Start date (YYYY-MM-DD or YYYY-MM-DD-HH:MM)
- end_date:   End date   (same format as start)

Optional params: organizations, time_block_status, worker (passed through
as query params if provided).

## Methods

- `async def execute(self, save_raw_response_path: Optional[str]=None, **query_params) -> pd.DataFrame` — Execute the REST custom report and return a DataFrame.
