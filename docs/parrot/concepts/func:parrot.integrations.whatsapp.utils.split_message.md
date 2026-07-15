---
type: Concept
title: split_message()
id: func:parrot.integrations.whatsapp.utils.split_message
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Split a long message into chunks that fit WhatsApp's message size limit.
---

# split_message

```python
def split_message(text: str, max_length: int=4096) -> List[str]
```

Split a long message into chunks that fit WhatsApp's message size limit.

Splits at natural boundaries (paragraphs, newlines, sentences) without
breaking code blocks.

Args:
    text: The text to split.
    max_length: Maximum characters per chunk (default 4096).

Returns:
    List of text chunks.
