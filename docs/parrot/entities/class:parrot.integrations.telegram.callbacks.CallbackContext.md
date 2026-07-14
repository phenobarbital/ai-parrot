---
type: Wiki Entity
title: CallbackContext
id: class:parrot.integrations.telegram.callbacks.CallbackContext
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Context object passed to @telegram_callback handlers.
---

# CallbackContext

Defined in [`parrot.integrations.telegram.callbacks`](../summaries/mod:parrot.integrations.telegram.callbacks.md).

```python
class CallbackContext
```

Context object passed to @telegram_callback handlers.

Attributes:
    prefix: The callback prefix that matched.
    payload: Decoded payload dict from callback_data.
    chat_id: Telegram chat ID.
    user_id: Telegram user ID who clicked the button.
    message_id: Message ID of the message containing the button.
    username: Telegram username (if available).
    raw_query: The original aiogram CallbackQuery object.

## Methods

- `def display_name(self) -> str` — Best available display name for the user.
