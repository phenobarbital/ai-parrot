---
type: Wiki Entity
title: WhatsAppHook
id: class:parrot.core.hooks.messaging.WhatsAppHook
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Receives WhatsApp webhook POSTs from Meta Cloud API.
---

# WhatsAppHook

Defined in [`parrot.core.hooks.messaging`](../summaries/mod:parrot.core.hooks.messaging.md).

```python
class WhatsAppHook(_MessagingHookBase)
```

Receives WhatsApp webhook POSTs from Meta Cloud API.

Handles both the verification challenge (GET) and incoming
message notifications (POST).

## Methods

- `def setup_routes(self, app: Any) -> None`
