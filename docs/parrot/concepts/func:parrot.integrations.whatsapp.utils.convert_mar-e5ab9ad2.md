---
type: Concept
title: convert_markdown_to_whatsapp()
id: func:parrot.integrations.whatsapp.utils.convert_markdown_to_whatsapp
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Convert standard Markdown to WhatsApp-compatible formatting.
---

# convert_markdown_to_whatsapp

```python
def convert_markdown_to_whatsapp(text: str) -> str
```

Convert standard Markdown to WhatsApp-compatible formatting.

WhatsApp supports:
- *bold* (not **bold**)
- _italic_ (same as standard MD single underscore)
- ~strikethrough~ (not ~~strikethrough~~)
- ```code``` (same as standard MD)

Standard MD -> WhatsApp:
- **bold** -> *bold*
- ~~strikethrough~~ -> ~strikethrough~
- Code blocks (```...```) are preserved as-is
