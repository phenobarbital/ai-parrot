---
type: Wiki Entity
title: OutputBridge
id: class:parrot.integrations.liveavatar.output_bridge.OutputBridge
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Publishes structured ai-parrot outputs to the AgentChat UI WS channel.
---

# OutputBridge

Defined in [`parrot.integrations.liveavatar.output_bridge`](../summaries/mod:parrot.integrations.liveavatar.output_bridge.md).

```python
class OutputBridge
```

Publishes structured ai-parrot outputs to the AgentChat UI WS channel.

Args:
    socket_manager: A ``UserSocketManager``-like object exposing
        ``async def broadcast_to_channel(channel, message, exclude_ws=None)``.
        Injected rather than imported to keep ``ai-parrot-integrations``
        decoupled from the server package and to allow fakes in tests.

## Methods

- `async def publish(self, msg: StructuredOutputMessage) -> None` — Publish a structured output to the channel keyed by ``session_id``.
