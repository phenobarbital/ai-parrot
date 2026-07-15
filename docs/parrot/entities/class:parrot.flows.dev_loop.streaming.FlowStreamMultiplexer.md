---
type: Wiki Entity
title: FlowStreamMultiplexer
id: class:parrot.flows.dev_loop.streaming.FlowStreamMultiplexer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Merge events from a flow stream and many dispatch streams.
---

# FlowStreamMultiplexer

Defined in [`parrot.flows.dev_loop.streaming`](../summaries/mod:parrot.flows.dev_loop.streaming.md).

```python
class FlowStreamMultiplexer
```

Merge events from a flow stream and many dispatch streams.

## Methods

- `async def replay(self) -> AsyncIterator[Dict[str, Any]]` — Replay historical events from every subscribed stream.
- `async def tail(self) -> AsyncIterator[Dict[str, Any]]` — Forward live events as they arrive.
- `async def close(self) -> None` — Stop the tail loop. Idempotent.
