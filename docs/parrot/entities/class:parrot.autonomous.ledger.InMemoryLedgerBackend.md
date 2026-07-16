---
type: Wiki Entity
title: InMemoryLedgerBackend
id: class:parrot.autonomous.ledger.InMemoryLedgerBackend
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: In-memory ``EventLedger`` implementation for use in tests and CI.
relates_to:
- concept: class:parrot.autonomous.ledger.EventLedger
  rel: extends
---

# InMemoryLedgerBackend

Defined in [`parrot.autonomous.ledger`](../summaries/mod:parrot.autonomous.ledger.md).

```python
class InMemoryLedgerBackend(EventLedger)
```

In-memory ``EventLedger`` implementation for use in tests and CI.

Replicates the exact semantics of ``PostgresLedgerBackend``:
monotonic ``seq``, correct filtering, ``find_incomplete`` logic.

No external dependencies required.

## Methods

- `async def append(self, event: LedgerEvent) -> int` — Assign a monotonic seq and store the event in memory.
- `async def read(self, *, agent_id: Optional[str]=None, since_seq: Optional[int]=None, event_class: Optional[str]=None, limit: int=100) -> list[LedgerEvent]` — Return filtered events ordered by seq ascending.
- `async def last_state(self, agent_id: str) -> AgentLedgerState` — Compute the activity projection from in-memory events.
- `async def find_incomplete(self) -> list[IncompleteExecution]` — Find traces with an opening event but no closing event.
