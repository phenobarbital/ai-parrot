---
type: Concept
title: iter_jsonl()
id: func:parrot.outputs.a2ui.serialization.iter_jsonl
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse a JSONL payload into A2UI messages, one per non-empty line.
---

# iter_jsonl

```python
def iter_jsonl(text: str) -> Iterator[A2UIMessageBase]
```

Parse a JSONL payload into A2UI messages, one per non-empty line.

Args:
    text: A JSONL string.

Yields:
    Concrete A2UI messages in line order.
