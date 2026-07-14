---
type: Wiki Entity
title: CallbackResult
id: class:parrot.integrations.telegram.callbacks.CallbackResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Result returned by a @telegram_callback handler.
---

# CallbackResult

Defined in [`parrot.integrations.telegram.callbacks`](../summaries/mod:parrot.integrations.telegram.callbacks.md).

```python
class CallbackResult
```

Result returned by a @telegram_callback handler.

All fields are optional — the wrapper will apply whichever are set.

Attributes:
    answer_text: Toast notification shown to the user (up to 200 chars).
    show_alert: If True, answer_text is shown as a modal alert instead of toast.
    edit_message: Replace the original message text with this.
    edit_parse_mode: Parse mode for edit_message (default: Markdown).
    reply_text: Send a new message as reply to the callback message.
    reply_parse_mode: Parse mode for reply_text.
    reply_markup: New InlineKeyboardMarkup to replace the current one.
                  Set to None (default) to keep existing, or pass an empty
                  dict/markup to remove buttons.
    remove_keyboard: If True, removes inline keyboard from original message.
