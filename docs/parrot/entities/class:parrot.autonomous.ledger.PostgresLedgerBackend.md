---
type: Wiki Entity
title: PostgresLedgerBackend
id: class:parrot.autonomous.ledger.PostgresLedgerBackend
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Postgres append-only implementation of ``EventLedger``.
relates_to:
- concept: class:parrot.autonomous.ledger.EventLedger
  rel: extends
---

# PostgresLedgerBackend

Defined in [`parrot.autonomous.ledger`](../summaries/mod:parrot.autonomous.ledger.md).

```python
class PostgresLedgerBackend(EventLedger)
```

Postgres append-only implementation of ``EventLedger``.

Uses the ``asyncdb`` pattern (``app["database"]`` / ``db.acquire()``)
consistent with the rest of the server layer.

Args:
    db: An asyncdb database instance (``app["database"]``).
    config: Optional ``LedgerConfig``; defaults are used if not provided.

## Methods

- `async def ensure_schema(self) -> None` — Execute the idempotent DDL statements against the database.
- `async def append(self, event: LedgerEvent) -> int` — Insert an event row and return the assigned ``BIGSERIAL`` seq.
- `async def read(self, *, agent_id: Optional[str]=None, since_seq: Optional[int]=None, event_class: Optional[str]=None, limit: int=100) -> list[LedgerEvent]` — Return filtered ledger events ordered by seq.
- `async def last_state(self, agent_id: str) -> AgentLedgerState` — Return the latest activity projection for an agent.
- `async def find_incomplete(self) -> list[IncompleteExecution]` — Find traces with an opening event but no closing event.
