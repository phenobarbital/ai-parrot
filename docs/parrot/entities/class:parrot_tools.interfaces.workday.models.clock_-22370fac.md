---
type: Wiki Entity
title: ClockEventResult
id: class:parrot_tools.interfaces.workday.models.clock_event.ClockEventResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Per-row submission outcome echoed back into the flow (G6).
---

# ClockEventResult

Defined in [`parrot_tools.interfaces.workday.models.clock_event`](../summaries/mod:parrot_tools.interfaces.workday.models.clock_event.md).

```python
class ClockEventResult(BaseModel)
```

Per-row submission outcome echoed back into the flow (G6).

Notes:
    - ``Put_Time_Clock_Events`` returns ONLY ``Response_Text`` — no
      per-event WID (verified Workday WWS v46.1).  ``event_id`` carries
      the CLIENT-assigned ``Time_Clock_Event_ID`` we sent (echoed back);
      ``submitted``/``error`` are atomic per batch.
    - ``Import_*`` responses return a single ``Import_Process_Reference``
      (async — not awaited, see Non-Goals).  ``event_id`` is that
      reference, repeated on every row.

Args:
    submitted: ``True`` if the event was accepted; ``False`` on fault.
    event_id: For Put — the client-assigned ``Time_Clock_Event_ID``.
        For Import — the batch ``Import_Process_Reference``.
    error: Fault message when ``submitted=False``; ``None`` on success.
