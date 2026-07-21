---
type: Wiki Entity
title: EventEmitterMixin
id: class:parrot.core.events.lifecycle.mixin.EventEmitterMixin
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Mixin providing a uniform ``self.events: EventRegistry`` interface.'
---

# EventEmitterMixin

Defined in [`parrot.core.events.lifecycle.mixin`](../summaries/mod:parrot.core.events.lifecycle.mixin.md).

```python
class EventEmitterMixin
```

Mixin providing a uniform ``self.events: EventRegistry`` interface.

Usage::

    class MyAgent(EventEmitterMixin, SomeBase):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._init_events()   # call AFTER super().__init__()

Subclasses MUST call :meth:`_init_events` from their ``__init__`` after
their base class initialisation.  The mixin itself does NOT call
``super().__init__()`` to avoid disturbing the host class's MRO.

If a host class accesses ``self.events`` without calling ``_init_events()``,
a default registry is lazily created (forwards to global) so no
``AttributeError`` is raised.

## Methods

- `def events(self) -> EventRegistry` — The per-instance event registry.
