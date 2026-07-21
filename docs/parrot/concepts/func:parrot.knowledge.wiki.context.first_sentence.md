---
type: Concept
title: first_sentence()
id: func:parrot.knowledge.wiki.context.first_sentence
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return the lead sentence of ``text``, hard-capped at ``max_chars``.
---

# first_sentence

```python
def first_sentence(text: str, max_chars: int=_MAX_LEAD_CHARS) -> str
```

Return the lead sentence of ``text``, hard-capped at ``max_chars``.

Args:
    text: Source text (summary or body).
    max_chars: Maximum characters returned.

Returns:
    The first sentence (or the truncated text when no sentence
    boundary is found), single-line.
