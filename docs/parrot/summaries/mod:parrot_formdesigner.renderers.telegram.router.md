---
type: Wiki Summary
title: parrot_formdesigner.renderers.telegram.router
id: mod:parrot_formdesigner.renderers.telegram.router
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Telegram form conversation router.
relates_to:
- concept: class:parrot_formdesigner.renderers.telegram.router.FormFilling
  rel: defines
- concept: class:parrot_formdesigner.renderers.telegram.router.TelegramFormRouter
  rel: defines
- concept: mod:parrot_formdesigner.renderers.telegram.models
  rel: references
- concept: mod:parrot_formdesigner.renderers.telegram.renderer
  rel: references
- concept: mod:parrot_formdesigner.services.registry
  rel: references
- concept: mod:parrot_formdesigner.services.validators
  rel: references
---

# `parrot_formdesigner.renderers.telegram.router`

Telegram form conversation router.

An aiogram Router that handles multi-step form conversations via inline
keyboards (FSMContext) and WebApp data submissions.

## Classes

- **`FormFilling(StatesGroup)`** — FSM state for an active form conversation.
- **`TelegramFormRouter(Router)`** — aiogram Router that handles form conversations.
