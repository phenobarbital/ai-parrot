---
type: Wiki Summary
title: parrot.forms.options
id: mod:parrot.forms.options
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Field option definitions for select and multi-select fields.
relates_to:
- concept: class:parrot.forms.options.FieldOption
  rel: defines
- concept: class:parrot.forms.options.OptionsSource
  rel: defines
- concept: mod:parrot.forms.types
  rel: references
---

# `parrot.forms.options`

Field option definitions for select and multi-select fields.

This module defines the data models for static options and dynamic
options sources that can be loaded from external services.

## Classes

- **`FieldOption(BaseModel)`** — A single option in a select or multi-select field.
- **`OptionsSource(BaseModel)`** — Dynamic options source configuration for fetching options at runtime.
