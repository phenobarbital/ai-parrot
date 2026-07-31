---
type: Wiki Entity
title: ClientStreamChunkEvent
id: class:parrot.core.events.lifecycle.events.client.ClientStreamChunkEvent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Emitted for each chunk received during a streaming response.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# ClientStreamChunkEvent

Defined in [`parrot.core.events.lifecycle.events.client`](../summaries/mod:parrot.core.events.lifecycle.events.client.md).

```python
class ClientStreamChunkEvent(LifecycleEvent)
```

Emitted for each chunk received during a streaming response.

HIGH-FREQUENCY event. This event NEVER dual-emits to EventBus by default,
even if a subscription has forward_to_bus=True — subscribers must
explicitly request bus forwarding.

Contains chunk metadata only (index + size), NEVER the chunk text,
to avoid PII leakage and keep per-chunk overhead minimal.

Attributes:
    client_name: Provider identifier.
    model: Model name/identifier.
    chunk_index: Zero-based index of this chunk in the stream.
    chunk_size_bytes: UTF-8 encoded byte length of this chunk.
