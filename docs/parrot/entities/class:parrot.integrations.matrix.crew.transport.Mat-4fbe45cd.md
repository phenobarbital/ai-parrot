---
type: Wiki Entity
title: MatrixCrewTransport
id: class:parrot.integrations.matrix.crew.transport.MatrixCrewTransport
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Top-level orchestrator for a Matrix multi-agent crew.
---

# MatrixCrewTransport

Defined in [`parrot.integrations.matrix.crew.transport`](../summaries/mod:parrot.integrations.matrix.crew.transport.md).

```python
class MatrixCrewTransport
```

Top-level orchestrator for a Matrix multi-agent crew.

Manages the ``MatrixAppService``, coordinator, registry, and per-agent
wrappers.  Supports ``async with`` for lifecycle management.

Usage::

    transport = MatrixCrewTransport.from_yaml("matrix_crew.yaml")
    async with transport:
        # Crew is running — blocks until context exits
        ...

Args:
    config: Validated ``MatrixCrewConfig`` instance.

## Methods

- `def from_yaml(cls, path: str) -> 'MatrixCrewTransport'` — Load crew configuration from a YAML file.
- `async def start(self) -> None` — Initialize and start all crew components.
- `async def stop(self) -> None` — Graceful shutdown: stop coordinator, unregister agents, stop AS.
- `async def on_room_message(self, room_id: str, sender: str, body: str, event_id) -> None` — Route an incoming Matrix room message to the correct agent wrapper.
