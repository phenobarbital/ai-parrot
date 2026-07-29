---
type: Wiki Summary
title: parrot_formdesigner.services.validators
id: mod:parrot_formdesigner.services.validators
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Platform-agnostic form validation for FormSchema.
relates_to:
- concept: class:parrot_formdesigner.services.validators.FormValidator
  rel: defines
- concept: class:parrot_formdesigner.services.validators.ValidationResult
  rel: defines
- concept: mod:parrot_formdesigner.core.constraints
  rel: references
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.core.types
  rel: references
- concept: mod:parrot_formdesigner.services.auth_context
  rel: references
- concept: mod:parrot_formdesigner.services.remote_response_resolver
  rel: references
- concept: mod:parrot_formdesigner.services.rest_field_resolver
  rel: references
---

# `parrot_formdesigner.services.validators`

Platform-agnostic form validation for FormSchema.

This module provides FormValidator and ValidationResult for validating
form submission data against FormSchema constraints. The validator is
async-native to support ASYNC_REMOTE and UNIQUE validation callbacks.

Migrated and enhanced from parrot/integrations/msteams/dialogs/validator.py.

## Classes

- **`ValidationResult(BaseModel)`** — Result of validating a form submission.
- **`FormValidator`** — Platform-agnostic validator for FormSchema data.
