---
type: Wiki Entity
title: ImportTimeClockEventsType
id: class:parrot_tools.interfaces.workday.handlers.import_time_clock_events.ImportTimeClockEventsType
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handler for ``Import_Time_Clock_Events`` (batch async import).
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayWriteTypeBase
  rel: extends
---

# ImportTimeClockEventsType

Defined in [`parrot_tools.interfaces.workday.handlers.import_time_clock_events`](../summaries/mod:parrot_tools.interfaces.workday.handlers.import-649a8cfe.md).

```python
class ImportTimeClockEventsType(WorkdayWriteTypeBase)
```

Handler for ``Import_Time_Clock_Events`` (batch async import).

The response carries a single ``Import_Process_Reference`` for the whole
batch; this reference is echoed as ``event_id`` on every output row.
No terminal-status polling is performed (Non-Goal).

Args:
    service: ``WorkdayService`` instance.

## Methods

- `def build_request(self, events: List[ClockEvent], batch_id: Optional[str]=None, **kwargs) -> dict` — Build the Import_Time_Clock_Events SOAP body.
- `def parse_ack(self, raw: Any) -> pd.DataFrame` — Parse Put_Import_Process_ResponseType into a per-row status DataFrame.
- `async def execute(self, events: List[ClockEvent], batch_id: Optional[str]=None, **kwargs) -> pd.DataFrame` — Execute Import_Time_Clock_Events and return per-row status DataFrame.
