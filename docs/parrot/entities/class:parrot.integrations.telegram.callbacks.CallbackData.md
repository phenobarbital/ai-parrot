---
type: Wiki Entity
title: CallbackData
id: class:parrot.integrations.telegram.callbacks.CallbackData
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Encode/decode callback_data for Telegram InlineKeyboardButtons.
---

# CallbackData

Defined in [`parrot.integrations.telegram.callbacks`](../summaries/mod:parrot.integrations.telegram.callbacks.md).

```python
class CallbackData
```

Encode/decode callback_data for Telegram InlineKeyboardButtons.

Format: ``prefix:json_payload``

Telegram limits callback_data to **64 bytes**, so payloads must be compact.
Use short keys and values.

Usage:
    # Encoding
    data = CallbackData.encode("tsel", {"t": "NAV-123", "d": "dev1"})
    # -> 'tsel:{"t":"NAV-123","d":"dev1"}'

    # Decoding
    prefix, payload = CallbackData.decode(data)
    # -> ("tsel", {"t": "NAV-123", "d": "dev1"})

## Methods

- `def encode(cls, prefix: str, payload: Dict[str, Any]) -> str` — Encode a prefix + payload into callback_data string.
- `def decode(cls, data: str) -> tuple[str, Dict[str, Any]]` — Decode callback_data into (prefix, payload).
