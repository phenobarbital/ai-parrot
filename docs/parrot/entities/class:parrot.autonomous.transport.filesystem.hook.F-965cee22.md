---
type: Wiki Entity
title: FilesystemHook
id: class:parrot.autonomous.transport.filesystem.hook.FilesystemHook
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Hook connecting agents to FilesystemTransport.
relates_to:
- concept: class:parrot.core.hooks.base.BaseHook
  rel: extends
---

# FilesystemHook

Defined in [`parrot.autonomous.transport.filesystem.hook`](../summaries/mod:parrot.autonomous.transport.filesystem.hook.md).

```python
class FilesystemHook(BaseHook)
```

Hook connecting agents to FilesystemTransport.

Listens to the agent's inbox for incoming messages and dispatches
them as ``HookEvent`` instances via ``on_event()``. Follows the
``WhatsAppRedisHook`` pattern exactly.

Supports ``command_prefix`` and ``allowed_agents`` filtering.

Args:
    config: FilesystemHookConfig with transport and filtering settings.
    **kwargs: Additional keyword arguments passed to BaseHook.

## Methods

- `async def start(self) -> None` — Start the transport and begin listening for messages.
- `async def stop(self) -> None` — Stop listening and shut down the transport.
