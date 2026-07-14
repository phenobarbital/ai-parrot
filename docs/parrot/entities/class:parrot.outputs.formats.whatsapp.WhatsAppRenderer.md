---
type: Wiki Entity
title: WhatsAppRenderer
id: class:parrot.outputs.formats.whatsapp.WhatsAppRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Renderer for WhatsApp output — returns plain text.
relates_to:
- concept: class:parrot.outputs.formats.base.BaseRenderer
  rel: extends
---

# WhatsAppRenderer

Defined in [`parrot.outputs.formats.whatsapp`](../summaries/mod:parrot.outputs.formats.whatsapp.md).

```python
class WhatsAppRenderer(BaseRenderer)
```

Renderer for WhatsApp output — returns plain text.

## Methods

- `async def render(self, response: Any, environment: str='default', export_format: str='html', include_code: bool=False, **kwargs) -> Tuple[str, Any]` — Render response as plain text for WhatsApp.
