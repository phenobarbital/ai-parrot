---
type: Wiki Entity
title: HookManager
id: class:parrot.core.hooks.manager.HookManager
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Manages registration, startup, and shutdown of all external hooks.
---

# HookManager

Defined in [`parrot.core.hooks.manager`](../summaries/mod:parrot.core.hooks.manager.md).

```python
class HookManager
```

Manages registration, startup, and shutdown of all external hooks.

The manager injects a callback into each hook so that fired events
flow into the orchestrator's execution pipeline.

Optionally, an :class:`EventBus` can be attached via
:meth:`set_event_bus` to enable distributed dual-emit: every hook
event is forwarded to both the direct callback *and* the bus on
channel ``hooks.<hook_type>.<event_type>``.

## Methods

- `def set_event_callback(self, callback) -> None` — Set the async callback that all hooks will invoke on events.
- `def set_event_bus(self, bus: 'EventBus') -> None` — Attach an :class:`EventBus` for distributed event publishing.
- `def register(self, hook: BaseHook) -> str` — Register a hook and return its hook_id.
- `def unregister(self, hook_id: str) -> Optional[BaseHook]` — Unregister a hook by ID. Returns the removed hook or None.
- `def get_hook(self, hook_id: str) -> Optional[BaseHook]` — Retrieve a registered hook by ID.
- `async def start_all(self) -> None` — Start all enabled hooks.
- `async def stop_all(self) -> None` — Stop all running hooks.
- `def setup_routes(self, app: Any) -> None` — Delegate route setup to HTTP-based hooks.
- `def hooks(self) -> List[BaseHook]` — List all registered hooks.
- `def stats(self) -> Dict[str, Any]` — Return summary statistics.
