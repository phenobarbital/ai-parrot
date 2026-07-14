---
type: Wiki Summary
title: parrot.forms.style
id: mod:parrot.forms.style
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Form presentation and layout style models.
relates_to:
- concept: class:parrot.forms.style.FieldSizeHint
  rel: defines
- concept: class:parrot.forms.style.FieldStyleHint
  rel: defines
- concept: class:parrot.forms.style.LayoutType
  rel: defines
- concept: class:parrot.forms.style.StyleSchema
  rel: defines
- concept: mod:parrot.forms.types
  rel: references
---

# `parrot.forms.style`

Form presentation and layout style models.

This module defines the StyleSchema and related models that control
how a FormSchema is presented visually, independently of the form
data definition.

## Classes

- **`LayoutType(str, Enum)`** — Available layout modes for form rendering.
- **`FieldSizeHint(str, Enum)`** — Size hints for individual form fields.
- **`FieldStyleHint(BaseModel)`** — Per-field style customization hints.
- **`StyleSchema(BaseModel)`** — Presentation style configuration for a form.
