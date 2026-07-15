---
type: Wiki Summary
title: parrot_formdesigner.extractors.pydantic
id: mod:parrot_formdesigner.extractors.pydantic
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pydantic model extractor for FormSchema generation.
relates_to:
- concept: class:parrot_formdesigner.extractors.pydantic.PydanticExtractor
  rel: defines
- concept: mod:parrot_formdesigner.core.constraints
  rel: references
- concept: mod:parrot_formdesigner.core.options
  rel: references
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.core.types
  rel: references
---

# `parrot_formdesigner.extractors.pydantic`

Pydantic model extractor for FormSchema generation.

Introspects Pydantic v2 BaseModel classes and produces FormSchema instances.
Supports type mapping, Optional/Literal/Enum handling, nested models,
list types, and Field() metadata extraction.

## Classes

- **`PydanticExtractor`** — Extracts FormSchema from Pydantic v2 BaseModel classes.
