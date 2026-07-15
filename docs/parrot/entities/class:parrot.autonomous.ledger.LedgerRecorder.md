---
type: Wiki Entity
title: LedgerRecorder
id: class:parrot.autonomous.ledger.LedgerRecorder
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Subscribe to the global lifecycle registry and persist all events.
---

# LedgerRecorder

Defined in [`parrot.autonomous.ledger`](../summaries/mod:parrot.autonomous.ledger.md).

```python
class LedgerRecorder
```

Subscribe to the global lifecycle registry and persist all events.

Uses an internal ``asyncio.Queue`` and a background flush task to avoid
blocking the agent hot-path. Events filtered by ``where`` are never
enqueued, so ``ClientStreamChunkEvent`` incurs zero overhead.

One ``LedgerRecorder`` per process — duplicate instances cause duplicate
ledger rows.

Args:
    ledger: An ``EventLedger`` backend instance.
    config: Optional ``LedgerConfig``; defaults are used if not provided.

## Methods

- `def start(self) -> None` — Subscribe to the global registry and start the background flush task.
- `async def stop(self) -> None` — Unsubscribe from the global registry and await the flush task.
- `async def on_event(self, evt: LifecycleEvent) -> None` — Convert a lifecycle event to a ``LedgerEvent`` and enqueue it.
