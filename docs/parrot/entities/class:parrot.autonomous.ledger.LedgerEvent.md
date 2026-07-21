---
type: Wiki Entity
title: LedgerEvent
id: class:parrot.autonomous.ledger.LedgerEvent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic wrapper for a single persisted lifecycle event.
---

# LedgerEvent

Defined in [`parrot.autonomous.ledger`](../summaries/mod:parrot.autonomous.ledger.md).

```python
class LedgerEvent(BaseModel)
```

Pydantic wrapper for a single persisted lifecycle event.

Attributes:
    seq: Monotonic sequence number assigned by the store. ``None``
        before the event has been persisted.
    event_id: UUID4 string from ``LifecycleEvent.event_id``.
    event_class: ``type(evt).__name__`` of the original lifecycle event.
    trace_id: ``evt.trace_context.trace_id`` for distributed correlation.
    source_type: Emitter category (``"agent"`` | ``"client"`` | ``"tool"``).
    source_name: Name of the specific emitter.
    agent_id: Agent identifier resolved from ``source_name``.
    timestamp: UTC datetime of the original event.
    event_data: Full JSON-safe dict from ``evt.to_dict()``.

## Methods

- `def from_lifecycle(cls, evt: LifecycleEvent) -> 'LedgerEvent'` — Construct a ``LedgerEvent`` from any ``LifecycleEvent``.
