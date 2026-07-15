---
type: Wiki Summary
title: parrot_formdesigner.core.options
id: mod:parrot_formdesigner.core.options
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Field option definitions for select and multi-select fields.
relates_to:
- concept: class:parrot_formdesigner.core.options.FieldOption
  rel: defines
- concept: class:parrot_formdesigner.core.options.OptionsSource
  rel: defines
- concept: mod:parrot_formdesigner.core.types
  rel: references
---

# `parrot_formdesigner.core.options`

Field option definitions for select and multi-select fields.

This module defines the data models for static options and dynamic
options sources that can be loaded from external services.

## Classes

- **`FieldOption(BaseModel)`** — A single option in a select or multi-select field.
- **`OptionsSource(BaseModel)`** — Dynamic options source configuration for fetching options at runtime.
