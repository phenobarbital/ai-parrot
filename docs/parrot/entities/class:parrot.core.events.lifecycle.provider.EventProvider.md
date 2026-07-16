---
type: Wiki Entity
title: EventProvider
id: class:parrot.core.events.lifecycle.provider.EventProvider
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Bundles multiple subscriber callbacks for batch registration.
---

# EventProvider

Defined in [`parrot.core.events.lifecycle.provider`](../summaries/mod:parrot.core.events.lifecycle.provider.md).

```python
class EventProvider(Protocol)
```

Bundles multiple subscriber callbacks for batch registration.

Implement ``register(registry)`` and call ``registry.subscribe()`` for
each callback you want to register.  Pass the provider to
``EventRegistry.add_provider(provider)`` to register all callbacks at
once and receive back the list of subscription IDs.

Example::

    class TelemetryProvider:
        def register(self, registry: EventRegistry) -> None:
            registry.subscribe(BeforeInvokeEvent, self.on_invoke_start)
            registry.subscribe(AfterInvokeEvent, self.on_invoke_end)
            registry.subscribe(InvokeFailedEvent, self.on_invoke_failed)

    reg = EventRegistry(forward_to_global=False)
    ids = reg.add_provider(TelemetryProvider())
    # ids contains 3 subscription IDs

Note:
    ``register()`` MUST be synchronous — subscriber registration happens
    at agent setup time, before any event loop is running.

## Methods

- `def register(self, registry: 'EventRegistry') -> None` — Register this provider's subscribers with *registry*.
