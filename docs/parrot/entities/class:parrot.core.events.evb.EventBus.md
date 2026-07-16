---
type: Wiki Entity
title: EventBus
id: class:parrot.core.events.evb.EventBus
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Bus de eventos con soporte para patrones glob y Redis como backend.
---

# EventBus

Defined in [`parrot.core.events.evb`](../summaries/mod:parrot.core.events.evb.md).

```python
class EventBus
```

Bus de eventos con soporte para patrones glob y Redis como backend.

Permite:
- Publicar eventos con tipos jerárquicos (order.created, order.updated)
- Subscribirse con patrones glob (order.*, *.created)
- Filtros personalizados por subscriber
- Backend en memoria o Redis para distribución

## Methods

- `async def connect(self)` — Conecta al backend Redis si está configurado.
- `async def close(self)` — Cierra conexiones.
- `def subscribe(self, pattern: str, handler: Callable[[Event], Any], *, priority: int=0, filter_fn: Optional[Callable[[Event], bool]]=None) -> str` — Subscribe a eventos que coincidan con el patrón.
- `def unsubscribe(self, subscriber_id: str) -> bool` — Elimina una subscripción.
- `async def publish(self, event: Event) -> int` — Publica un evento al bus.
- `async def start_redis_listener(self)` — Inicia listener de Redis para eventos distribuidos.
- `async def emit(self, event_type: str, payload: Dict[str, Any], **kwargs) -> int` — Shortcut para publicar eventos.
- `def on(self, pattern: str, **kwargs)` — Decorator para subscribirse a eventos.
