---
type: Wiki Summary
title: parrot_formdesigner.renderers
id: mod:parrot_formdesigner.renderers
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Form renderers for the forms abstraction layer.
relates_to:
- concept: mod:parrot_formdesigner
  rel: references
---

# `parrot_formdesigner.renderers`

Form renderers for the forms abstraction layer.

Renderers convert FormSchema + StyleSchema into platform-specific output:
- AdaptiveCardRenderer: Adaptive Card JSON for MS Teams
- HTML5Renderer: HTML5 form fragment for web
- JsonSchemaRenderer: JSON Schema output for custom frontends
- TelegramRenderer: Telegram inline keyboards / WebApp for Telegram bots
