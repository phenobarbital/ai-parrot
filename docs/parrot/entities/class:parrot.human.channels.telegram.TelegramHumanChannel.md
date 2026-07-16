---
type: Wiki Entity
title: TelegramHumanChannel
id: class:parrot.human.channels.telegram.TelegramHumanChannel
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Telegram channel for Human-in-the-Loop interactions.
relates_to:
- concept: class:parrot.human.channels.base.HumanChannel
  rel: extends
---

# TelegramHumanChannel

Defined in [`parrot.human.channels.telegram`](../summaries/mod:parrot.human.channels.telegram.md).

```python
class TelegramHumanChannel(HumanChannel)
```

Telegram channel for Human-in-the-Loop interactions.

Translates HumanInteraction objects into Telegram-native UI:
- Approval → Two inline buttons (✅ Approve / ❌ Reject)
- Single choice → Inline keyboard with one button per option
- Multi choice → Toggle buttons + Done button
- Free text → Text prompt, human replies with a message
- Poll → Telegram native poll (for consensus/voting)
- Form → Sequential text prompts (simplified in Telegram)

All callbacks use secure, single-use tokens stored in Redis
to prevent unauthorized responses and replay attacks.

Args:
    bot: aiogram Bot instance (can be shared with TelegramBotManager).
    redis: Async Redis client.
    token_ttl: TTL for callback tokens in seconds (default: 24h).
    parse_mode: Telegram message parse mode.

## Methods

- `async def register_response_handler(self, callback: Callable[[HumanResponse], Awaitable[None]]) -> None` — Register the manager's response callback.
- `async def register_cancel_handler(self, callback: Callable[[str, str], Awaitable[bool]]) -> None` — Register the manager's cancel callback (cancel_pending).
- `async def send_interaction(self, interaction: HumanInteraction, recipient: str) -> bool` — Send an interaction to a human via Telegram private chat.
- `async def send_notification(self, recipient: str, message: str) -> None` — Send a simple text notification.
- `async def cancel_interaction(self, interaction_id: str, recipient: str) -> bool` — Cancel/withdraw an interaction by removing its keyboard.
- `async def close(self) -> None` — Release transcriber resources (call on bot shutdown).
