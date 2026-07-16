---
type: Wiki Summary
title: parrot_formdesigner.tools.edit_toolkit
id: mod:parrot_formdesigner.tools.edit_toolkit
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: EditToolkit — LLM-callable toolkit for surgical FormSchema editing.
relates_to:
- concept: class:parrot_formdesigner.tools.edit_toolkit.EditToolkit
  rel: defines
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
- concept: mod:parrot_formdesigner.api.operations
  rel: references
- concept: mod:parrot_formdesigner.core.constraints
  rel: references
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.services.validators
  rel: references
---

# `parrot_formdesigner.tools.edit_toolkit`

EditToolkit — LLM-callable toolkit for surgical FormSchema editing.

Implements FEAT-169: instead of sending the full FormSchema JSON to the LLM,
this toolkit exposes 12 focused tools that allow the LLM to inspect and mutate
the form in surgical, targeted operations.

Tool categories:
- Inspection (4): get_form_summary, get_section, get_field, search_fields
- Mutation (7):   update_field, add_field, remove_field, add_section,
                  update_section, move_field, update_form_meta
- Control (1):    done

## Classes

- **`EditToolkit(AbstractToolkit)`** — Toolkit exposing FormSchema inspection and mutation as LLM-callable tools.
