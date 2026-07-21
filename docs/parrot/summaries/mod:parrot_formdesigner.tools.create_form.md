---
type: Wiki Summary
title: parrot_formdesigner.tools.create_form
id: mod:parrot_formdesigner.tools.create_form
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: CreateFormTool — LLM-driven form generation tool.
relates_to:
- concept: class:parrot_formdesigner.tools.create_form.CreateFormInput
  rel: defines
- concept: class:parrot_formdesigner.tools.create_form.CreateFormTool
  rel: defines
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot_formdesigner.api._utils
  rel: references
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.services.registry
  rel: references
- concept: mod:parrot_formdesigner.services.validators
  rel: references
- concept: mod:parrot_formdesigner.tools.edit_toolkit
  rel: references
- concept: mod:parrot_formdesigner.tools.field_helpers
  rel: references
---

# `parrot_formdesigner.tools.create_form`

CreateFormTool — LLM-driven form generation tool.

Accepts a natural language prompt and returns a validated FormSchema.
Supports iterative refinement: when refine_form_id is provided, loads
the existing form and asks the LLM to modify it.

Flow:
1. Build a structured system prompt with FormSchema JSON structure
2. If refine_form_id, load existing form from registry and include in prompt
3. Call LLM client to generate JSON
4. Parse and validate against FormSchema (retry up to 2 times with error feedback)
5. Validate generated form using FormValidator (circular dependency check)
6. Optionally register in FormRegistry with persist=True
7. Return FormSchema in ToolResult metadata

## Classes

- **`CreateFormInput(BaseModel)`** — Input schema for the create_form tool.
- **`CreateFormTool(AbstractTool)`** — Create a FormSchema from a natural language prompt using an LLM.
