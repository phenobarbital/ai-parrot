---
type: Wiki Entity
title: ImportReportedTimeBlocksType
id: class:parrot_tools.interfaces.workday.handlers.import_reported_time_blocks.ImportReportedTimeBlocksType
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handler for ``Import_Reported_Time_Blocks`` (batch async import).
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayWriteTypeBase
  rel: extends
---

# ImportReportedTimeBlocksType

Defined in [`parrot_tools.interfaces.workday.handlers.import_reported_time_blocks`](../summaries/mod:parrot_tools.interfaces.workday.handlers.import-0a3490b1.md).

```python
class ImportReportedTimeBlocksType(WorkdayWriteTypeBase)
```

Handler for ``Import_Reported_Time_Blocks`` (batch async import).

Args:
    service: ``WorkdayService`` instance.

## Methods

- `def build_request(self, blocks: List[ReportedTimeBlock], **kwargs) -> dict` — Build the Import_Reported_Time_Blocks SOAP body.
- `def parse_ack(self, raw: Any) -> pd.DataFrame` — Parse Put_Import_Process_ResponseType into a per-row status DataFrame.
- `async def execute(self, blocks: List[ReportedTimeBlock], **kwargs) -> pd.DataFrame` — Execute Import_Reported_Time_Blocks and return per-row status DataFrame.
