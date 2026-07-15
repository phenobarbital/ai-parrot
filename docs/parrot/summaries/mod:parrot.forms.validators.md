---
type: Wiki Summary
title: parrot.forms.validators
id: mod:parrot.forms.validators
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Platform-agnostic form validation for FormSchema.
relates_to:
- concept: class:parrot.forms.validators.FormValidator
  rel: defines
- concept: class:parrot.forms.validators.ValidationResult
  rel: defines
- concept: mod:parrot.forms.schema
  rel: references
- concept: mod:parrot.forms.types
  rel: references
---

# `parrot.forms.validators`

Platform-agnostic form validation for FormSchema.

This module provides FormValidator and ValidationResult for validating
form submission data against FormSchema constraints. The validator is
async-native to support ASYNC_REMOTE and UNIQUE validation callbacks.

Migrated and enhanced from parrot/integrations/msteams/dialogs/validator.py.

## Classes

- **`ValidationResult(BaseModel)`** — Result of validating a form submission.
- **`FormValidator`** — Platform-agnostic validator for FormSchema data.
