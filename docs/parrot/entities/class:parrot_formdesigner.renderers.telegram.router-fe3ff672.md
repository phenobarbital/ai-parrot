---
type: Wiki Entity
title: TelegramFormRouter
id: class:parrot_formdesigner.renderers.telegram.router.TelegramFormRouter
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: aiogram Router that handles form conversations.
---

# TelegramFormRouter

Defined in [`parrot_formdesigner.renderers.telegram.router`](../summaries/mod:parrot_formdesigner.renderers.telegram.router.md).

```python
class TelegramFormRouter(Router)
```

aiogram Router that handles form conversations.

Supports inline keyboard multi-step flows via FSMContext and
WebApp data reception. Can be included in any aiogram Dispatcher.

Args:
    renderer: TelegramRenderer for rendering forms.
    registry: FormRegistry for looking up forms by ID.
    validator: Optional FormValidator. Created if not provided.
    on_submit: Optional callback invoked after successful validation.
        Signature: ``async def on_submit(form_id, data, chat_id) -> None``

## Methods

- `async def start_form(self, form_id: str, chat_id: int, bot: Bot, state: FSMContext, mode: TelegramRenderMode=TelegramRenderMode.AUTO, *, tenant: str | None=None) -> None` — Initiate a form conversation in the given chat.
