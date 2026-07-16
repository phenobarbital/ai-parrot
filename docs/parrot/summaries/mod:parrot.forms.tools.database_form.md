---
type: Wiki Summary
title: parrot.forms.tools.database_form
id: mod:parrot.forms.tools.database_form
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: DatabaseFormTool — Load a form definition from PostgreSQL into a FormSchema.
relates_to:
- concept: class:parrot.forms.tools.database_form.DatabaseFormInput
  rel: defines
- concept: class:parrot.forms.tools.database_form.DatabaseFormTool
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.forms.constraints
  rel: references
- concept: mod:parrot.forms.options
  rel: references
- concept: mod:parrot.forms.registry
  rel: references
- concept: mod:parrot.forms.schema
  rel: references
- concept: mod:parrot.forms.types
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.forms.tools.database_form`

DatabaseFormTool — Load a form definition from PostgreSQL into a FormSchema.

Queries the ``networkninja.forms`` + ``networkninja.form_metadata`` tables by
``formid`` and ``orgid``, deterministically maps the result to a ``FormSchema``,
and optionally persists it in the ``FormRegistry``.

Transformation pipeline:
1. Query — fetch form + metadata in one parameterized SQL call via asyncdb
2. Index — build metadata lookup by column_name and question_id → column_name reverse index
3. Pre-scan — collect multi-select option values from conditional references
4. Map sections — each question_block → FormSection
5. Map fields — each question → FormField (skip if unsupported or not in metadata)
6. Map logic — logic_groups → DependencyRule with ConditionOperator.EQ
7. Map validations — responseRequired → required=True
8. Register — store FormSchema in FormRegistry

## Classes

- **`DatabaseFormInput(BaseModel)`** — Input schema for DatabaseFormTool.
- **`DatabaseFormTool(AbstractTool)`** — Load a form definition from PostgreSQL into a FormSchema.
