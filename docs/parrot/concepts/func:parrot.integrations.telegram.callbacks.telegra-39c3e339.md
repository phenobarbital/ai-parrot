---
type: Concept
title: telegram_callback()
id: func:parrot.integrations.telegram.callbacks.telegram_callback
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Decorator to register an agent method as a Telegram inline callback handler.
---

# telegram_callback

```python
def telegram_callback(prefix: str, description: str='')
```

Decorator to register an agent method as a Telegram inline callback handler.

The method will be called when a user clicks an InlineKeyboardButton
whose ``callback_data`` starts with the given prefix.

Args:
    prefix: Unique prefix string that identifies this callback.
            Must be short (recommended ≤8 chars) to leave room for payload
            within Telegram's 64-byte callback_data limit.
    description: Human-readable description of what this callback does.

The decorated method must have signature:
    async def handler(self, callback: CallbackContext) -> CallbackResult

Usage:
    @telegram_callback(prefix="tsel", description="Select ticket for today")
    async def on_ticket_selected(self, callback: CallbackContext) -> CallbackResult:
        ticket_key = callback.payload["t"]
        # ... do work ...
        return CallbackResult(
            answer_text="✅ Done",
            edit_message=f"Selected: {ticket_key}"
        )
