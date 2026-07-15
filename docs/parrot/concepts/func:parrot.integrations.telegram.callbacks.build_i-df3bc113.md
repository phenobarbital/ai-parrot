---
type: Concept
title: build_inline_keyboard()
id: func:parrot.integrations.telegram.callbacks.build_inline_keyboard
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build an InlineKeyboardMarkup dict compatible with aiogram.
---

# build_inline_keyboard

```python
def build_inline_keyboard(buttons: List[List[Dict[str, Any]]]) -> Dict[str, Any]
```

Build an InlineKeyboardMarkup dict compatible with aiogram.

Each button dict should have:
    - text: str — Button label
    - callback_data: str — Already-encoded callback data

Or use the helper:
    - text: str
    - prefix: str + payload: dict → auto-encodes callback_data

Args:
    buttons: 2D list of button dicts (rows × columns).

Returns:
    InlineKeyboardMarkup-compatible dict.

Usage:
    keyboard = build_inline_keyboard([
        [{"text": "▶️ NAV-123", "prefix": "tsel", "payload": {"t": "NAV-123"}}],
        [{"text": "⏭️ Skip", "prefix": "tskip", "payload": {}}],
    ])
