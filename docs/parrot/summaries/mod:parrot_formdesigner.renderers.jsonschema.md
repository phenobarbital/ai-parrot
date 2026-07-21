---
type: Wiki Summary
title: parrot_formdesigner.renderers.jsonschema
id: mod:parrot_formdesigner.renderers.jsonschema
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: JSON Schema renderer for FormSchema.
relates_to:
- concept: class:parrot_formdesigner.renderers.jsonschema.JsonSchemaRenderer
  rel: defines
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.core.style
  rel: references
- concept: mod:parrot_formdesigner.core.types
  rel: references
- concept: mod:parrot_formdesigner.renderers.base
  rel: references
---

# `parrot_formdesigner.renderers.jsonschema`

JSON Schema renderer for FormSchema.

Renders FormSchema as a structural JSON Schema with custom x- extensions,
suitable for consumption by custom form-builder components (e.g., Svelte).

Output:
- content: structural JSON Schema dict (type=object, properties, required)
- style_output: StyleSchema.model_dump() dict
- content_type: "application/schema+json"

## Classes

- **`JsonSchemaRenderer(AbstractFormRenderer)`** — Renders FormSchema as a structural JSON Schema with x- extensions.
