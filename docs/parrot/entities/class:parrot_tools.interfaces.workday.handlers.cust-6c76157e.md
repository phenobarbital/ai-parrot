---
type: Wiki Entity
title: CustomPunchFieldReportType
id: class:parrot_tools.interfaces.workday.handlers.custom_punch_field_report.CustomPunchFieldReportType
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Handler for the Custom Punch - Field Report.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# CustomPunchFieldReportType

Defined in [`parrot_tools.interfaces.workday.handlers.custom_punch_field_report`](../summaries/mod:parrot_tools.interfaces.workday.handlers.custom-60a9db47.md).

```python
class CustomPunchFieldReportType(WorkdayTypeBase)
```

Handler for the Custom Punch - Field Report.

This report provides detailed punch/time entry information including:
- Worker and position details
- Punch in/out times
- Cost center and location (default and override)
- Calculated quantities and tags
- Wages and rates

## Methods

- `async def execute(self, **kwargs) -> pd.DataFrame` — Execute the Custom Punch - Field Report.
