---
type: Wiki Entity
title: EventDeduplicator
id: class:parrot.integrations.slack.dedup.EventDeduplicator
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: In-memory event deduplication with TTL.
---

# EventDeduplicator

Defined in [`parrot.integrations.slack.dedup`](../summaries/mod:parrot.integrations.slack.dedup.md).

```python
class EventDeduplicator
```

In-memory event deduplication with TTL.

For single-instance deployments. Use RedisEventDeduplicator
for multi-instance production environments.

Args:
    ttl_seconds: Time-to-live for seen events (default: 300 seconds / 5 minutes).
    cleanup_interval: How often to run cleanup (default: 60 seconds).

Example:
    >>> dedup = EventDeduplicator(ttl_seconds=300)
    >>> await dedup.start()
    >>> if not dedup.is_duplicate("evt_123"):
    ...     # Process the event
    ...     pass
    >>> await dedup.stop()

## Methods

- `async def start(self) -> None` — Start the background cleanup task.
- `async def stop(self) -> None` — Stop the cleanup task.
- `def is_duplicate(self, event_id: Optional[str]) -> bool` — Check if event was already seen. Thread-safe for sync contexts.
- `def seen_count(self) -> int` — Return the number of events currently tracked.
- `def clear(self) -> None` — Clear all tracked events. Useful for testing.
