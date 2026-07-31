---
type: Concept
title: format_reply()
id: func:parrot.integrations.telegram.crew.mention.format_reply
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Format a response by prepending a mention to the text.
---

# format_reply

```python
def format_reply(mention: str, text: str) -> str
```

Format a response by prepending a mention to the text.

Args:
    mention: The @mention string to prepend.
    text: The response text body.

Returns:
    Combined string with mention on the first line,
    followed by the text on a new line.
