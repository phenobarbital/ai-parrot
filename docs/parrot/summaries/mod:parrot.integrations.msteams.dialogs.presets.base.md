---
type: Wiki Summary
title: parrot.integrations.msteams.dialogs.presets.base
id: mod:parrot.integrations.msteams.dialogs.presets.base
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Base Form Dialog with common functionality.
relates_to:
- concept: class:parrot.integrations.msteams.dialogs.presets.base.BaseFormDialog
  rel: defines
- concept: func:parrot.integrations.msteams.dialogs.presets.base.get_registered_form
  rel: defines
- concept: func:parrot.integrations.msteams.dialogs.presets.base.register_form
  rel: defines
- concept: mod:parrot.forms
  rel: references
- concept: mod:parrot.forms.renderers
  rel: references
- concept: mod:parrot.forms.validators
  rel: references
---

# `parrot.integrations.msteams.dialogs.presets.base`

Base Form Dialog with common functionality.

## Classes

- **`BaseFormDialog(ComponentDialog)`** — Base class for all form dialog presets.

## Functions

- `def register_form(form: FormSchema, style: Optional[StyleSchema]=None) -> None` — Register a form and optional style in the global registry for later lookup.
- `def get_registered_form(form_id: str) -> Optional[tuple[FormSchema, Optional[StyleSchema]]]` — Get a form and style from the global registry.
