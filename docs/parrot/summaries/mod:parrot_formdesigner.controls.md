---
type: Wiki Summary
title: parrot_formdesigner.controls
id: mod:parrot_formdesigner.controls
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Form-control registry — extensible toolbar metadata.
relates_to:
- concept: mod:parrot_formdesigner
  rel: references
---

# `parrot_formdesigner.controls`

Form-control registry — extensible toolbar metadata.

Public API:

    from parrot_formdesigner.controls import (
        register_field_control, get_controls, iter_controls,
        FieldControlMetadata,
    )

Importing ``parrot_formdesigner.controls.builtin`` seeds the registry with
one entry per ``FieldType`` value. The default seed is loaded by
``parrot_formdesigner.api.__init__`` so that ``GET /api/v1/form-controls``
returns the full list from day one.
