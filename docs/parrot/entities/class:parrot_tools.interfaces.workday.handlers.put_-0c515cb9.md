---
type: Wiki Entity
title: PutTimeClockEventsType
id: class:parrot_tools.interfaces.workday.handlers.put_time_clock_events.PutTimeClockEventsType
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Handler for ``Put_Time_Clock_Events`` (real-time clock-event submission).
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayWriteTypeBase
  rel: extends
---

# PutTimeClockEventsType

Defined in [`parrot_tools.interfaces.workday.handlers.put_time_clock_events`](../summaries/mod:parrot_tools.interfaces.workday.handlers.put_ti-91a18a55.md).

```python
class PutTimeClockEventsType(WorkdayWriteTypeBase)
```

Handler for ``Put_Time_Clock_Events`` (real-time clock-event submission).

Args:
    service: ``WorkdayService`` instance (provides ``call_operation``).
    events: Validated ``list[ClockEvent]`` — set by the caller via ``execute``.

## Methods

- `def build_request(self, events: List[ClockEvent], **kwargs) -> dict` — Build the Put_Time_Clock_Events SOAP body.
- `def parse_ack(self, raw: Any) -> pd.DataFrame` — Parse Put_Time_Clock_Events_Response into a per-row status DataFrame.
- `async def execute(self, events: List[ClockEvent], **kwargs) -> pd.DataFrame` — Execute Put_Time_Clock_Events and return per-row status DataFrame.
