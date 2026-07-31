---
type: Concept
title: to_jsonl()
id: func:parrot.outputs.a2ui.serialization.to_jsonl
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Serialize one or more messages to JSONL (one complete message per line).
---

# to_jsonl

```python
def to_jsonl(messages: A2UIMessageBase | Iterable[A2UIMessageBase]) -> str
```

Serialize one or more messages to JSONL (one complete message per line).

Args:
    messages: A single message or an iterable of messages.

Returns:
    A JSONL string; each line is a complete, parseable A2UI message.
