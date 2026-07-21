---
type: Wiki Summary
title: parrot_formdesigner.ui
id: mod:parrot_formdesigner.ui
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: parrot_formdesigner.ui — HTML pages + Telegram WebApp surface.
relates_to:
- concept: mod:parrot_formdesigner
  rel: references
---

# `parrot_formdesigner.ui`

parrot_formdesigner.ui — HTML pages + Telegram WebApp surface.

Public API:

    from parrot_formdesigner.ui import setup_form_ui

Importing this package does NOT trigger ``parrot_formdesigner.api`` —
the two are independently mountable. Hard-imports navigator-auth (same
policy as api/).
