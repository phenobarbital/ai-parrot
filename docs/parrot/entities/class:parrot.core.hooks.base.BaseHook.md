---
type: Wiki Entity
title: BaseHook
id: class:parrot.core.hooks.base.BaseHook
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract base for all external hooks in AutonomousOrchestrator.
---

# BaseHook

Defined in [`parrot.core.hooks.base`](../summaries/mod:parrot.core.hooks.base.md).

```python
class BaseHook(ABC)
```

Abstract base for all external hooks in AutonomousOrchestrator.

Concrete hooks must implement ``start()`` and ``stop()``.
When an external event fires, the hook calls ``on_event()`` which
delegates to the registered callback (set by ``HookManager``).

For HTTP-based hooks (Jira, Upload, SharePoint), override
``setup_routes(app)`` to register aiohttp handlers.

## Methods

- `def set_callback(self, callback: Callable[[HookEvent], Coroutine[Any, Any, None]]) -> None` — Set the async callback invoked when an event fires.
- `async def on_event(self, event_data: HookEvent) -> None` — Emit a HookEvent to the orchestrator via the registered callback.
- `async def start(self) -> None` — Start listening for external events.
- `async def stop(self) -> None` — Stop listening and release resources.
- `def setup_routes(self, app: Any) -> None` — Register aiohttp routes. Override in HTTP-based hooks.
