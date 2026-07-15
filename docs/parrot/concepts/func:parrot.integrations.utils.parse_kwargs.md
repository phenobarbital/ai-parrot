---
type: Concept
title: parse_kwargs()
id: func:parrot.integrations.utils.parse_kwargs
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse 'key=val key2="quoted val"' into a kwargs dict.
---

# parse_kwargs

```python
def parse_kwargs(text: str) -> dict
```

Parse 'key=val key2="quoted val"' into a kwargs dict.

Supports quoted values so multi-word strings survive as a single value:
    report="Read this loudly" max_lines=5

Non key=val tokens become positional: arg0, arg1, etc.

Args:
    text: The argument string to parse.

Returns:
    Dict of parsed keyword arguments.
