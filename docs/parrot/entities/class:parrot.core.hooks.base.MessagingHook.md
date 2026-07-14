---
type: Wiki Entity
title: MessagingHook
id: class:parrot.core.hooks.base.MessagingHook
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Interface for messaging-channel hooks (e.g. matrix, telegram).
---

# MessagingHook

Defined in [`parrot.core.hooks.base`](../summaries/mod:parrot.core.hooks.base.md).

```python
class MessagingHook(Protocol)
```

Interface for messaging-channel hooks (e.g. matrix, telegram).

Satellite packages implement this protocol and register themselves
with :class:`HookRegistry`.  The core ``AutonomousOrchestrator``
can then discover and start messaging hooks without a direct
compile-time dependency on any channel SDK.

## Methods

- `async def start(self) -> None` — Start listening for external events.
- `async def stop(self) -> None` — Stop listening and release resources.
- `async def on_message(self, message: Any) -> None` — Handle an incoming message from the channel.
