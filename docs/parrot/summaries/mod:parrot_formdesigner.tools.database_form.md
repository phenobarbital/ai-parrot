---
type: Wiki Summary
title: parrot_formdesigner.tools.database_form
id: mod:parrot_formdesigner.tools.database_form
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: DatabaseFormTool — thin dispatcher over an AbstractFormService.
relates_to:
- concept: class:parrot_formdesigner.tools.database_form.DatabaseFormInput
  rel: defines
- concept: class:parrot_formdesigner.tools.database_form.DatabaseFormTool
  rel: defines
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot_formdesigner.services.registry
  rel: references
- concept: mod:parrot_formdesigner.tools.services
  rel: references
---

# `parrot_formdesigner.tools.database_form`

DatabaseFormTool — thin dispatcher over an AbstractFormService.

Resolves the requested service by name, runs fetch + to_form_schema, then
registers the resulting FormSchema in the FormRegistry.

## Classes

- **`DatabaseFormInput(BaseModel)`** — Input schema for DatabaseFormTool — service-aware.
- **`DatabaseFormTool(AbstractTool)`** — Load a form definition from a configured form-source service into a FormSchema.
