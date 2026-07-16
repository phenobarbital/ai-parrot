---
type: Wiki Entity
title: WebhookSubscriber
id: class:parrot.core.events.lifecycle.subscribers.webhook.WebhookSubscriber
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: EventProvider that POSTs serialized lifecycle events to an HTTPS endpoint.
---

# WebhookSubscriber

Defined in [`parrot.core.events.lifecycle.subscribers.webhook`](../summaries/mod:parrot.core.events.lifecycle.subscribers.webhook.md).

```python
class WebhookSubscriber
```

EventProvider that POSTs serialized lifecycle events to an HTTPS endpoint.

Args:
    url: Destination endpoint URL.
    secret: Optional secret for HMAC-SHA256 signing.  When set, the
        ``X-Parrot-Signature: sha256=<hex>`` header is included.
    event_classes: Optional sequence of ``LifecycleEvent`` subclasses to
        subscribe to.  Defaults to ``[LifecycleEvent]`` (all events).
    max_attempts: Maximum number of POST attempts per event (default 3).
    timeout_seconds: Per-request timeout in seconds (default 5.0).
    forward_to_bus: Whether to forward to ``EventBus`` (default False).

## Methods

- `def register(self, registry: 'EventRegistry') -> None` — Register subscribers for each configured event class.
- `async def aclose(self) -> None` — Close the underlying ``aiohttp.ClientSession``.
