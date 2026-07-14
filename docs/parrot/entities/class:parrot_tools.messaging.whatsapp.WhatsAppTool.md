---
type: Wiki Entity
title: WhatsAppTool
id: class:parrot_tools.messaging.whatsapp.WhatsAppTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Send WhatsApp messages through the whatsmeow bridge.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# WhatsAppTool

Defined in [`parrot_tools.messaging.whatsapp`](../summaries/mod:parrot_tools.messaging.whatsapp.md).

```python
class WhatsAppTool(AbstractTool)
```

Send WhatsApp messages through the whatsmeow bridge.

This tool communicates with the Go-based WhatsApp Bridge to send messages.
The bridge handles authentication, session management, and message delivery.

Features:
- Send text messages
- Send media (images, videos, documents)
- Check connection status
- Automatic reconnection handling

Examples:
    # Send simple text message
    await tool.execute(
        phone="14155552671",
        message="Hello from AI-Parrot!"
    )

    # Send message with image
    await tool.execute(
        phone="14155552671",
        message="Check out this chart",
        media_url="https://example.com/chart.png"
    )
