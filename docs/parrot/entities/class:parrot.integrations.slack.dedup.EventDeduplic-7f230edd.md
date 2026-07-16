---
type: Wiki Entity
title: EventDeduplicatorProtocol
id: class:parrot.integrations.slack.dedup.EventDeduplicatorProtocol
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Protocol for event deduplication backends.
---

# EventDeduplicatorProtocol

Defined in [`parrot.integrations.slack.dedup`](../summaries/mod:parrot.integrations.slack.dedup.md).

```python
class EventDeduplicatorProtocol(Protocol)
```

Protocol for event deduplication backends.

Both in-memory and Redis-backed implementations follow this interface.

## Methods

- `def is_duplicate(self, event_id: str) -> bool` — Check if an event has been seen before.
- `async def start(self) -> None` — Start the deduplicator (e.g., cleanup tasks).
- `async def stop(self) -> None` — Stop the deduplicator and clean up resources.
