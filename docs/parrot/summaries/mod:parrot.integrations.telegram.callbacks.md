---
type: Wiki Summary
title: parrot.integrations.telegram.callbacks
id: mod:parrot.integrations.telegram.callbacks
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Telegram Callback Decorators.
relates_to:
- concept: class:parrot.integrations.telegram.callbacks.CallbackContext
  rel: defines
- concept: class:parrot.integrations.telegram.callbacks.CallbackData
  rel: defines
- concept: class:parrot.integrations.telegram.callbacks.CallbackMetadata
  rel: defines
- concept: class:parrot.integrations.telegram.callbacks.CallbackRegistry
  rel: defines
- concept: class:parrot.integrations.telegram.callbacks.CallbackResult
  rel: defines
- concept: func:parrot.integrations.telegram.callbacks.build_inline_keyboard
  rel: defines
- concept: func:parrot.integrations.telegram.callbacks.telegram_callback
  rel: defines
---

# `parrot.integrations.telegram.callbacks`

Telegram Callback Decorators.

Provides @telegram_callback decorator for agents to register
inline keyboard callback handlers, following the same pattern
as @telegram_command for commands.

Usage on an Agent:

    class JiraSpecialist(Agent):

        @telegram_callback(
            prefix="ticket_select",
            description="Handle ticket selection from daily standup"
        )
        async def on_ticket_selected(self, callback: CallbackContext) -> CallbackResult:
            ticket_key = callback.payload["ticket_key"]
            await self.transition_ticket(ticket_key, "In Progress")
            return CallbackResult(
                answer_text=f"✅ {ticket_key} → In Progress",
                edit_message=f"✅ Ticket *{ticket_key}* moved to *In Progress*. Let's get to work! 💪"
            )

## Classes

- **`CallbackContext`** — Context object passed to @telegram_callback handlers.
- **`CallbackResult`** — Result returned by a @telegram_callback handler.
- **`CallbackData`** — Encode/decode callback_data for Telegram InlineKeyboardButtons.
- **`CallbackMetadata`** — Metadata stored on a method decorated with @telegram_callback.
- **`CallbackRegistry`** — Discovers and stores @telegram_callback handlers from an agent.

## Functions

- `def telegram_callback(prefix: str, description: str='')` — Decorator to register an agent method as a Telegram inline callback handler.
- `def build_inline_keyboard(buttons: List[List[Dict[str, Any]]]) -> Dict[str, Any]` — Build an InlineKeyboardMarkup dict compatible with aiogram.
