---
type: Wiki Entity
title: WhatsAppRedisHook
id: class:parrot.core.hooks.whatsapp_redis.WhatsAppRedisHook
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: WhatsApp message listener via Redis Pub/Sub.
relates_to:
- concept: class:parrot.core.hooks.base.BaseHook
  rel: extends
---

# WhatsAppRedisHook

Defined in [`parrot.core.hooks.whatsapp_redis`](../summaries/mod:parrot.core.hooks.whatsapp_redis.md).

```python
class WhatsAppRedisHook(BaseHook)
```

WhatsApp message listener via Redis Pub/Sub.

Features:
- Listens to 'whatsapp:messages' (configurable)
- Filters by allowed_phones / allowed_groups
- Supports command_prefix
- Routes to specific agents based on keywords/phones via 'routes' config
- Auto-reply support with WhatsApp Bridge integration
- Session management per phone number

Example configuration::

    config = WhatsAppRedisHookConfig(
        name="whatsapp_hook",
        enabled=True,
        target_type="agent",
        target_id="CustomerServiceAgent",
        redis_url="redis://localhost:6379",
        channel="whatsapp:messages",
        command_prefix="!",
        allowed_phones=["14155552671", "34612345678"],
        auto_reply=True,
        routes=[
            {
                "name": "sales",
                "keywords": ["precio", "comprar", "venta"],
                "target_id": "SalesAgent",
                "target_type": "agent"
            },
            {
                "name": "vip_customer",
                "phones": ["14155551234"],
                "target_id": "VIPAgent",
                "target_type": "agent"
            }
        ]
    )

## Methods

- `async def start(self) -> None` — Start listening to Redis Pub/Sub for WhatsApp messages.
- `async def stop(self) -> None` — Stop listening and cleanup resources.
- `async def send_reply(self, phone: str, message: str) -> bool` — Send a WhatsApp reply via the bridge.
