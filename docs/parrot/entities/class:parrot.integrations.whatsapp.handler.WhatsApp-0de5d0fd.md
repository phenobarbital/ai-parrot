---
type: Wiki Entity
title: WhatsAppUserSession
id: class:parrot.integrations.whatsapp.handler.WhatsAppUserSession
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Per-user session tracking for WhatsApp conversations.
---

# WhatsAppUserSession

Defined in [`parrot.integrations.whatsapp.handler`](../summaries/mod:parrot.integrations.whatsapp.handler.md).

```python
class WhatsAppUserSession
```

Per-user session tracking for WhatsApp conversations.

Tracks conversation memory, message timestamps (for 24h window),
and per-user metadata.

Attributes:
    phone_number: The user's WhatsApp phone number (wa_id).
    conversation_memory: InMemoryConversation instance for this user.
    last_message_time: Timestamp of the user's last incoming message (UTC).
    message_count: Total messages received from this user.
    metadata: Arbitrary per-user metadata.

## Methods

- `def is_within_24h_window(self) -> bool` — Check if the user's last message is within the 24-hour messaging window.
- `def touch(self) -> None` — Update last message time and increment counter.
