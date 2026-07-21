---
type: Wiki Entity
title: TimeBlockType
id: class:parrot_tools.interfaces.workday.handlers.time_blocks.TimeBlockType
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handler for the Workday Get_Calculated_Time_Blocks operation.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# TimeBlockType

Defined in [`parrot_tools.interfaces.workday.handlers.time_blocks`](../summaries/mod:parrot_tools.interfaces.workday.handlers.time_blocks.md).

```python
class TimeBlockType(WorkdayTypeBase)
```

Handler for the Workday Get_Calculated_Time_Blocks operation.

## Methods

- `async def execute(self, **kwargs) -> pd.DataFrame` — Execute the Get_Calculated_Time_Blocks operation and return a pandas DataFrame.
- `async def get_time_blocks_by_worker(self, worker_id: str, start_date: Optional[str]=None, end_date: Optional[str]=None) -> pd.DataFrame` — Convenience method to get time blocks for a specific worker.
- `async def get_time_blocks_by_date_range(self, start_date: str, end_date: str, status: Optional[str]=None) -> pd.DataFrame` — Convenience method to get time blocks for a date range.
