---
type: Wiki Entity
title: CustomReportType
id: class:parrot_tools.interfaces.workday.handlers.custom_report.CustomReportType
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Generic handler for ANY Workday RaaS custom report.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# CustomReportType

Defined in [`parrot_tools.interfaces.workday.handlers.custom_report`](../summaries/mod:parrot_tools.interfaces.workday.handlers.custom_report.md).

```python
class CustomReportType(WorkdayTypeBase)
```

Generic handler for ANY Workday RaaS custom report.

This type can execute any Workday custom report by accepting:
- report_name: The name of the report in Workday
- report_owner: The email/ID of the report owner (optional, uses default)
- **query_params: Any report-specific parameters

The handler automatically:
- Builds the correct RaaS URL
- Authenticates with Basic Auth
- Converts XML response to DataFrame with dynamic parsing
- Handles nested structures and arrays appropriately

Example usage:
    # Time blocks report
    df = await custom_report.execute(
        report_name="Extract_Time_Blocks_-_Navigator",
        Start_Date="2025-11-17",
        End_Date="2025-11-17",
        Worker="12345"
    )

    # Different report with different parameters
    df = await custom_report.execute(
        report_name="Absence_Calendar_Report",
        Year="2025",
        Month="11"
    )

## Methods

- `async def execute(self, report_name: str, report_owner: Optional[str]=None, **query_params) -> pd.DataFrame` — Execute any Workday RaaS custom report.
