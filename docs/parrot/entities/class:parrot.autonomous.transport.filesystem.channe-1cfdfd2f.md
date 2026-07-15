---
type: Wiki Entity
title: ChannelManager
id: class:parrot.autonomous.transport.filesystem.channel.ChannelManager
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Broadcast channels using JSONL append-only files.
---

# ChannelManager

Defined in [`parrot.autonomous.transport.filesystem.channel`](../summaries/mod:parrot.autonomous.transport.filesystem.channel.md).

```python
class ChannelManager
```

Broadcast channels using JSONL append-only files.

Each channel is a separate ``.jsonl`` file in the channels directory.
Agents publish messages (append) and poll from a caller-managed offset.
No subscription state is maintained server-side.

All writes are serialized via an ``asyncio.Lock`` to prevent
interleaved output from concurrent coroutines.

Args:
    channels_dir: Path to the channels directory.
    config: Transport configuration.

## Methods

- `async def publish(self, channel: str, from_agent: str, from_name: str, content: str, payload: Optional[Dict[str, Any]]=None) -> None` — Publish a message to a broadcast channel.
- `async def poll(self, channel: str, since_offset: int=0) -> AsyncGenerator[Dict[str, Any], None]` — Poll messages from a channel starting at a given offset.
- `async def list_channels(self) -> List[str]` — List available channel names.
