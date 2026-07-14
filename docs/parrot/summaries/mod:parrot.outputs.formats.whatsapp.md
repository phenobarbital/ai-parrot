---
type: Wiki Summary
title: parrot.outputs.formats.whatsapp
id: mod:parrot.outputs.formats.whatsapp
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: WhatsApp output renderer.
relates_to:
- concept: class:parrot.outputs.formats.whatsapp.WhatsAppRenderer
  rel: defines
- concept: mod:parrot.models.outputs
  rel: references
- concept: mod:parrot.outputs.formats
  rel: references
- concept: mod:parrot.outputs.formats.base
  rel: references
---

# `parrot.outputs.formats.whatsapp`

WhatsApp output renderer.

Lightweight renderer that extracts plain text for WhatsApp delivery.
WhatsApp-specific formatting (bold, italic, monospace) is handled
downstream by `convert_markdown_to_whatsapp` in the bridge wrapper.

## Classes

- **`WhatsAppRenderer(BaseRenderer)`** — Renderer for WhatsApp output — returns plain text.
