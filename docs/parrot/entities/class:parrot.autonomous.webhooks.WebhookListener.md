---
type: Wiki Entity
title: WebhookListener
id: class:parrot.autonomous.webhooks.WebhookListener
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Listener HTTP para triggers externos.
---

# WebhookListener

Defined in [`parrot.autonomous.webhooks`](../summaries/mod:parrot.autonomous.webhooks.md).

```python
class WebhookListener
```

Listener HTTP para triggers externos.

Permite que sistemas externos disparen ejecuciones de agentes via webhooks.

## Methods

- `def set_executor(self, executor: Callable)` — Configura el ejecutor de agentes.
- `def set_event_bus(self, event_bus: 'EventBus')` — Conecta con el event bus para emitir eventos.
- `def register_endpoint(self, path: str, agent_name: str, **kwargs) -> WebhookEndpoint` — Registra un nuevo endpoint webhook.
- `def setup(self, app: web.Application)` — Configura las rutas en la aplicación aiohttp.
