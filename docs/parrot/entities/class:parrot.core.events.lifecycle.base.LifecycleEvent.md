---
type: Wiki Entity
title: LifecycleEvent
id: class:parrot.core.events.lifecycle.base.LifecycleEvent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Read-only base class for every lifecycle event.
---

# LifecycleEvent

Defined in [`parrot.core.events.lifecycle.base`](../summaries/mod:parrot.core.events.lifecycle.base.md).

```python
class LifecycleEvent(ABC)
```

Read-only base class for every lifecycle event.

Subclasses MUST be ``@dataclass(frozen=True)``. Attempts to mutate
instances raise ``FrozenInstanceError``.

All fields must be JSON-serializable (str, int, float, bool, None,
list, dict). Non-serializable values (e.g., live database connections)
must be excluded or referenced by ID — ``to_dict()`` enforces this
via a strict ``json.dumps`` validation pass.

Attributes:
    trace_context: W3C Trace Context for distributed trace identity.
        Required for every event — no default (callers must supply).
    event_id: Auto-generated UUID4 string uniquely identifying this
        event instance.
    timestamp: UTC datetime of event creation.
    source_type: String tag for the emitter type (``"agent"``,
        ``"client"``, ``"tool"``).
    source_name: Name of the specific emitter (agent name, client
        name, tool name).

## Methods

- `def to_dict(self) -> dict[str, Any]` — Serialize to a JSON-compatible dict with strict validation.
