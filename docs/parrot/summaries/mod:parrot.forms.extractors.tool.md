---
type: Wiki Summary
title: parrot.forms.extractors.tool
id: mod:parrot.forms.extractors.tool
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool extractor for FormSchema generation from AbstractTool instances.
relates_to:
- concept: class:parrot.forms.extractors.tool.ToolExtractor
  rel: defines
- concept: mod:parrot.forms.extractors.pydantic
  rel: references
- concept: mod:parrot.forms.schema
  rel: references
---

# `parrot.forms.extractors.tool`

Tool extractor for FormSchema generation from AbstractTool instances.

Extracts FormSchema from a tool's args_schema by delegating to PydanticExtractor
with tool-specific metadata (name, description) and field filtering.

## Classes

- **`ToolExtractor`** — Extracts FormSchema from AbstractTool.args_schema.
