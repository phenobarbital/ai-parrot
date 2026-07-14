---
type: Wiki Entity
title: WhatsAppBridgeWrapper
id: class:parrot.integrations.whatsapp.bridge_wrapper.WhatsAppBridgeWrapper
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Wraps an AI-Parrot Agent for WhatsApp Bridge integration.
---

# WhatsAppBridgeWrapper

Defined in [`parrot.integrations.whatsapp.bridge_wrapper`](../summaries/mod:parrot.integrations.whatsapp.bridge_wrapper.md).

```python
class WhatsAppBridgeWrapper
```

Wraps an AI-Parrot Agent for WhatsApp Bridge integration.

Features:
- Webhook endpoint receives messages from the Go bridge
- Per-phone conversation memory (like Telegram per-chat)
- Calls agent.ask() directly — no Redis intermediary
- Replies via bridge's HTTP /send endpoint
- Phone allowlist, /clear and /help commands

Usage::

    wrapper = WhatsAppBridgeWrapper(
        agent=my_agent,
        config=WhatsAppBridgeConfig(
            name="helper",
            chatbot_id="HelperAgent",
            bridge_url="http://localhost:8765",
        ),
        app=aiohttp_app,
    )

## Methods

- `def clear_session(self, phone_number: str) -> None` — Clear a user's conversation session.
