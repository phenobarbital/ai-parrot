---
type: Wiki Entity
title: HookableAgent
id: class:parrot.core.hooks.mixins.HookableAgent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Mixin that adds hook support to any agent or integration handler.
---

# HookableAgent

Defined in [`parrot.core.hooks.mixins`](../summaries/mod:parrot.core.hooks.mixins.md).

```python
class HookableAgent
```

Mixin that adds hook support to any agent or integration handler.

Provides a ``HookManager`` instance and convenience methods for
attaching, starting, stopping hooks and handling hook events.

Usage:
    class MyTelegramBot(TelegramAgentWrapper, HookableAgent):
        def __init__(self, ...):
            super().__init__(...)
            self._init_hooks()

        async def handle_hook_event(self, event: HookEvent) -> None:
            # Custom routing logic
            await self.process_message(event.task or str(event.payload))

Lifecycle
---------
Declare ``HookableAgent`` BEFORE the bot base in the class bases so
Python MRO routes ``super().cleanup()`` into the bot base's teardown:

    class MyAgent(HookableAgent, JiraSpecialist):  # correct
        ...

    class MyAgent(JiraSpecialist, HookableAgent):  # WRONG — super().cleanup()
        ...                                        # resolves to object

When the bot is registered with ``BotManager`` the cleanup chain fires
automatically on aiohttp ``on_cleanup``.

## Methods

- `def hook_manager(self) -> HookManager` — Access the underlying HookManager.
- `def attach_hook(self, hook: BaseHook) -> str` — Register a hook and return its hook_id.
- `async def start_hooks(self) -> None` — Start all registered hooks.
- `async def stop_hooks(self) -> None` — Stop all registered hooks.
- `async def handle_hook_event(self, event: HookEvent) -> None` — Handle an incoming hook event.
- `async def cleanup(self) -> None` — Stop hooks and delegate to the next class in MRO.
