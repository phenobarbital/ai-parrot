---
type: Wiki Summary
title: parrot_formdesigner.api
id: mod:parrot_formdesigner.api
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: parrot_formdesigner.api — JSON REST surface.
relates_to:
- concept: mod:parrot_formdesigner
  rel: references
---

# `parrot_formdesigner.api`

parrot_formdesigner.api — JSON REST surface.

Public API:

    from parrot_formdesigner.api import setup_form_api

Importing this package triggers two side effects:

1. ``parrot_formdesigner.controls.builtin`` is imported, seeding the
   form-control registry with one entry per ``FieldType``.
2. ``navigator_auth.decorators`` is imported (HARD dependency).

If ``navigator-auth`` is not installed, ``import parrot_formdesigner.api``
raises ``ImportError``.
