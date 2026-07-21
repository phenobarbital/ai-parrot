---
type: Wiki Summary
title: parrot.forms.extractors.pydantic
id: mod:parrot.forms.extractors.pydantic
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic model extractor for FormSchema generation.
relates_to:
- concept: class:parrot.forms.extractors.pydantic.PydanticExtractor
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

# `parrot.forms.extractors.pydantic`

Pydantic model extractor for FormSchema generation.

Introspects Pydantic v2 BaseModel classes and produces FormSchema instances.
Supports type mapping, Optional/Literal/Enum handling, nested models,
list types, and Field() metadata extraction.

## Classes

- **`PydanticExtractor`** — Extracts FormSchema from Pydantic v2 BaseModel classes.
