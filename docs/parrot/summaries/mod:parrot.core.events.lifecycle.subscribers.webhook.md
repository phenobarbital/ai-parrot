---
type: Wiki Summary
title: parrot.core.events.lifecycle.subscribers.webhook
id: mod:parrot.core.events.lifecycle.subscribers.webhook
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: WebhookSubscriber — HTTP POST lifecycle events to an external endpoint.
relates_to:
- concept: class:parrot.core.events.lifecycle.subscribers.webhook.WebhookSubscriber
  rel: defines
- concept: mod:parrot.core.events.lifecycle.base
  rel: references
- concept: mod:parrot.core.events.lifecycle.registry
  rel: references
---

# `parrot.core.events.lifecycle.subscribers.webhook`

WebhookSubscriber — HTTP POST lifecycle events to an external endpoint.

FEAT-176 — Lifecycle Events System.

``WebhookSubscriber`` is an ``EventProvider`` that serialises each lifecycle
event to JSON and POSTs it to a configured HTTPS endpoint.  Key features:

- **Optional HMAC-SHA256 signing**: include ``X-Parrot-Signature: sha256=<hex>``
  for endpoint verification.
- **Bounded retry**: up to ``max_attempts`` retries on 5xx / connection errors,
  with exponential backoff.  Permanent 4xx responses are logged and dropped.
- **Efficient session reuse**: one ``aiohttp.ClientSession`` per subscriber;
  call ``aclose()`` to release it at shutdown.
- **Selective subscription**: pass ``event_classes`` to restrict which event
  types trigger a POST (default: all ``LifecycleEvent`` subclasses).

## Classes

- **`WebhookSubscriber`** — EventProvider that POSTs serialized lifecycle events to an HTTPS endpoint.
