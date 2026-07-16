---
type: Wiki Entity
title: WhatsAppAgentWrapper
id: class:parrot.integrations.whatsapp.wrapper.WhatsAppAgentWrapper
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wraps an AI-Parrot Agent for WhatsApp integration.
---

# WhatsAppAgentWrapper

Defined in [`parrot.integrations.whatsapp.wrapper`](../summaries/mod:parrot.integrations.whatsapp.wrapper.md).

```python
class WhatsAppAgentWrapper
```

Wraps an AI-Parrot Agent for WhatsApp integration.

Features:
- Webhook-based message reception (GET verification + POST updates)
- Per-user conversation memory via WhatsAppUserSession
- WhatsApp-compatible markdown formatting
- Message splitting for long responses
- Image and document sending
- Phone number allowlist authorization
- 24-hour messaging window tracking

## Methods

- `def clear_session(self, phone_number: str) -> None` — Clear a user's conversation session.
