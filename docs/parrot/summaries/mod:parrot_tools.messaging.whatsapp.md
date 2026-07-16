---
type: Wiki Summary
title: parrot_tools.messaging.whatsapp
id: mod:parrot_tools.messaging.whatsapp
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: WhatsApp Tool - Send and receive WhatsApp messages via whatsmeow bridge.
relates_to:
- concept: class:parrot_tools.messaging.whatsapp.WhatsAppSendInput
  rel: defines
- concept: class:parrot_tools.messaging.whatsapp.WhatsAppTool
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot_tools.abstract
  rel: references
---

# `parrot_tools.messaging.whatsapp`

WhatsApp Tool - Send and receive WhatsApp messages via whatsmeow bridge.

## Classes

- **`WhatsAppSendInput(BaseModel)`** — Input schema for sending WhatsApp messages.
- **`WhatsAppTool(AbstractTool)`** — Send WhatsApp messages through the whatsmeow bridge.
