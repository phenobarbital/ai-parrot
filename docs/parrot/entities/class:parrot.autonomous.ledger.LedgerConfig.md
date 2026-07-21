---
type: Wiki Entity
title: LedgerConfig
id: class:parrot.autonomous.ledger.LedgerConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configuration for the ledger recorder and backend.
---

# LedgerConfig

Defined in [`parrot.autonomous.ledger`](../summaries/mod:parrot.autonomous.ledger.md).

```python
class LedgerConfig(BaseModel)
```

Configuration for the ledger recorder and backend.

Attributes:
    enabled: Whether the recorder is active.
    exclude_event_classes: Set of ``__name__`` strings to filter out.
        ``ClientStreamChunkEvent`` is excluded by default to avoid
        flooding the ledger with high-frequency stream events.
    batch_size: Maximum number of events to flush per batch iteration.
    table_name: Postgres table name (must match DDL).

## Methods

- `def validate_table_name(cls, v: str) -> str` — Ensure table_name is a safe SQL identifier (alphanumeric + underscore).
