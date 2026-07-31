---
type: Wiki Summary
title: parrot_formdesigner.renderers.telegram.renderer
id: mod:parrot_formdesigner.renderers.telegram.renderer
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Telegram form renderer.
relates_to:
- concept: class:parrot_formdesigner.renderers.telegram.renderer.TelegramRenderer
  rel: defines
- concept: mod:parrot_formdesigner.core.options
  rel: references
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.core.style
  rel: references
- concept: mod:parrot_formdesigner.core.types
  rel: references
- concept: mod:parrot_formdesigner.renderers.base
  rel: references
- concept: mod:parrot_formdesigner.renderers.telegram.models
  rel: references
---

# `parrot_formdesigner.renderers.telegram.renderer`

Telegram form renderer.

Analyzes a FormSchema and produces either inline keyboard steps
or a WebApp URL, returned as a TelegramFormPayload inside RenderedForm.

## Classes

- **`TelegramRenderer(AbstractFormRenderer)`** — Renders FormSchema as Telegram interactions.
