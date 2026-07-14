---
type: Wiki Entity
title: ActivityFeed
id: class:parrot.autonomous.transport.filesystem.feed.ActivityFeed
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Global append-only JSONL event log for the FilesystemTransport.
---

# ActivityFeed

Defined in [`parrot.autonomous.transport.filesystem.feed`](../summaries/mod:parrot.autonomous.transport.filesystem.feed.md).

```python
class ActivityFeed
```

Global append-only JSONL event log for the FilesystemTransport.

Every system event (agent join/leave, message delivery, broadcast,
reservation) is recorded as a single JSON line. The feed auto-rotates
when it exceeds ``feed_retention`` lines, keeping only the most recent
entries.

All writes are serialized via an ``asyncio.Lock`` to prevent
interleaved output from concurrent coroutines.

Args:
    feed_path: Path to the JSONL feed file.
    config: Transport configuration.

## Methods

- `async def emit(self, event: str, data: Dict[str, Any] | None=None) -> None` — Append an event to the activity feed.
- `async def tail(self, n: int=50) -> List[Dict[str, Any]]` — Read the last *n* events from the feed.
