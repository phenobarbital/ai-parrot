---
type: Wiki Entity
title: TimeBlockReportType
id: class:parrot_tools.interfaces.workday.handlers.time_block_report.TimeBlockReportType
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handler for the Extract Time Blocks Navigator custom report.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# TimeBlockReportType

Defined in [`parrot_tools.interfaces.workday.handlers.time_block_report`](../summaries/mod:parrot_tools.interfaces.workday.handlers.time_b-8f981bbf.md).

```python
class TimeBlockReportType(WorkdayTypeBase)
```

Handler for the Extract Time Blocks Navigator custom report.

## Methods

- `async def execute(self, **kwargs) -> pd.DataFrame` — Execute the Extract Time Blocks Navigator report using REST API.
