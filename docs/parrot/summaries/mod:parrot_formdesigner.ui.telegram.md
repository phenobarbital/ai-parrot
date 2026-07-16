---
type: Wiki Summary
title: parrot_formdesigner.ui.telegram
id: mod:parrot_formdesigner.ui.telegram
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Telegram WebApp handlers for parrot-formdesigner.
relates_to:
- concept: class:parrot_formdesigner.ui.telegram.TelegramWebAppHandler
  rel: defines
- concept: mod:parrot_formdesigner.renderers.html5
  rel: references
- concept: mod:parrot_formdesigner.services.registry
  rel: references
- concept: mod:parrot_formdesigner.services.validators
  rel: references
---

# `parrot_formdesigner.ui.telegram`

Telegram WebApp handlers for parrot-formdesigner.

Serves forms as Telegram WebApps with the JS SDK embedded, and provides
a REST fallback endpoint for payloads exceeding the 4 KB sendData() limit.

## Classes

- **`TelegramWebAppHandler`** — Serves forms as Telegram WebApps and handles REST fallback submissions.
