---
type: Wiki Entity
title: EventLedger
id: class:parrot.autonomous.ledger.EventLedger
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract interface for the persistent event ledger.
---

# EventLedger

Defined in [`parrot.autonomous.ledger`](../summaries/mod:parrot.autonomous.ledger.md).

```python
class EventLedger(ABC)
```

Abstract interface for the persistent event ledger.

All writes are append-only. Implementations MUST guarantee a
monotonically increasing ``seq`` on every ``append`` call.

## Methods

- `async def append(self, event: LedgerEvent) -> int` — Persist a ledger event and return its assigned ``seq``.
- `async def read(self, *, agent_id: Optional[str]=None, since_seq: Optional[int]=None, event_class: Optional[str]=None, limit: int=100) -> list[LedgerEvent]` — Return ledger events matching the given filters.
- `async def last_state(self, agent_id: str) -> AgentLedgerState` — Return the latest activity projection for an agent.
- `async def find_incomplete(self) -> list[IncompleteExecution]` — Detect executions with an opening event but no matching closing event.
