---
type: Wiki Summary
title: parrot_formdesigner.renderers.telegram.models
id: mod:parrot_formdesigner.renderers.telegram.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Data models for the Telegram form renderer.
relates_to:
- concept: class:parrot_formdesigner.renderers.telegram.models.FormActionCallback
  rel: defines
- concept: class:parrot_formdesigner.renderers.telegram.models.FormFieldCallback
  rel: defines
- concept: class:parrot_formdesigner.renderers.telegram.models.TelegramFormPayload
  rel: defines
- concept: class:parrot_formdesigner.renderers.telegram.models.TelegramFormStep
  rel: defines
- concept: class:parrot_formdesigner.renderers.telegram.models.TelegramRenderMode
  rel: defines
- concept: mod:parrot_formdesigner.core.types
  rel: references
---

# `parrot_formdesigner.renderers.telegram.models`

Data models for the Telegram form renderer.

Defines enums, Pydantic models, and aiogram CallbackData factories
used by TelegramRenderer and TelegramFormRouter.

## Classes

- **`TelegramRenderMode(str, Enum)`** — Rendering mode for Telegram forms.
- **`TelegramFormStep(BaseModel)`** — A single step in an inline keyboard form conversation.
- **`TelegramFormPayload(BaseModel)`** — Output of TelegramRenderer.render(), stored in RenderedForm.content.
- **`FormFieldCallback(CallbackData)`** — Compact callback data for inline form field selections.
- **`FormActionCallback(CallbackData)`** — Callback data for form-level actions (submit, cancel).
