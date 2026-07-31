---
type: Wiki Summary
title: parrot.forms.renderers.jsonschema
id: mod:parrot.forms.renderers.jsonschema
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: JSON Schema renderer for FormSchema.
relates_to:
- concept: class:parrot.forms.renderers.jsonschema.JsonSchemaRenderer
  rel: defines
- concept: mod:parrot.forms.constraints
  rel: references
- concept: mod:parrot.forms.options
  rel: references
- concept: mod:parrot.forms.renderers.base
  rel: references
- concept: mod:parrot.forms.schema
  rel: references
- concept: mod:parrot.forms.style
  rel: references
- concept: mod:parrot.forms.types
  rel: references
---

# `parrot.forms.renderers.jsonschema`

JSON Schema renderer for FormSchema.

Renders FormSchema as a structural JSON Schema with custom x- extensions,
suitable for consumption by custom form-builder components (e.g., Svelte).

Output:
- content: structural JSON Schema dict (type=object, properties, required)
- style_output: StyleSchema.model_dump() dict
- content_type: "application/schema+json"

## Classes

- **`JsonSchemaRenderer(AbstractFormRenderer)`** — Renders FormSchema as a structural JSON Schema with x- extensions.
