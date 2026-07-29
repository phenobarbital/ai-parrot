---
type: Wiki Entity
title: EventRegistry
id: class:parrot.core.events.lifecycle.registry.EventRegistry
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Typed lifecycle event dispatcher.
---

# EventRegistry

Defined in [`parrot.core.events.lifecycle.registry`](../summaries/mod:parrot.core.events.lifecycle.registry.md).

```python
class EventRegistry
```

Typed lifecycle event dispatcher.

Args:
    event_bus: Optional ``EventBus`` instance for dual-emit subscribers.
    bus_channel_prefix: Prefix for ``EventBus`` channel names.
        Final channel: ``f"{prefix}.{EventClassName}"``.
        Defaults to ``"lifecycle"``.
    forward_to_global: When ``True`` (default), each emitted event is
        also forwarded to the process-wide global registry via
        ``get_global_registry()``. Set ``False`` in unit tests to keep
        tests isolated from the global singleton.

## Methods

- `def subscribe(self, event_type: Type[E], callback: AsyncSubscriber, *, where: 'Optional[Callable[[E], bool]]'=None, forward_to_bus: bool=False) -> str` — Register an async subscriber for *event_type* (and its subclasses).
- `def unsubscribe(self, subscription_id: str) -> bool` — Remove a subscription by its ID.
- `def has_subscribers(self, event_type: Type[E]) -> bool` — Return ``True`` if any subscriber would receive *event_type*.
- `def add_provider(self, provider: Any) -> list[str]` — Register all subscriptions declared by an ``EventProvider``.
- `async def emit(self, event: LifecycleEvent) -> None` — Dispatch *event* to all matching subscribers.
- `def emit_nowait(self, event: LifecycleEvent) -> None` — Schedule :meth:`emit` on the running event loop, or drop silently.
- `def forward_to_global(self, event: LifecycleEvent) -> None` — Forward *event* to the global registry regardless of ``forward_to_global``.
