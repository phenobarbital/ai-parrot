---
type: Wiki Entity
title: IncompleteExecution
id: class:parrot.autonomous.ledger.IncompleteExecution
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: An execution that was opened (Before*) but never closed (After*/Failed*).
---

# IncompleteExecution

Defined in [`parrot.autonomous.ledger`](../summaries/mod:parrot.autonomous.ledger.md).

```python
class IncompleteExecution(BaseModel)
```

An execution that was opened (Before*) but never closed (After*/Failed*).

Populated by ``EventLedger.find_incomplete()`` and consumed by
``AutonomousOrchestrator.resume()`` to re-enqueue stalled work.

Attributes:
    trace_id: Distributed trace ID that identifies this execution.
    agent_id: Agent that started the execution (may be None).
    event_class: Class name of the opening event.
    event_data: ``event_data`` dict from the opening event.
    timestamp: When the opening event was recorded.
    last_seq: Sequence number of the most recent event in this trace.
