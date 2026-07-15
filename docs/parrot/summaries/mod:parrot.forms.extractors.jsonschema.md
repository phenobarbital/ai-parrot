---
type: Wiki Summary
title: parrot.forms.extractors.jsonschema
id: mod:parrot.forms.extractors.jsonschema
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: JSON Schema extractor for FormSchema generation.
relates_to:
- concept: class:parrot.forms.extractors.jsonschema.JsonSchemaExtractor
  rel: defines
- concept: mod:parrot.forms.constraints
  rel: references
- concept: mod:parrot.forms.options
  rel: references
- concept: mod:parrot.forms.schema
  rel: references
- concept: mod:parrot.forms.types
  rel: references
---

# `parrot.forms.extractors.jsonschema`

JSON Schema extractor for FormSchema generation.

Converts standard JSON Schema dicts into FormSchema instances.
Supports type mapping, constraint extraction, $ref resolution,
format keywords, enum conversion, and oneOf/anyOf union types.

## Classes

- **`JsonSchemaExtractor`** — Converts JSON Schema dicts into FormSchema instances.
