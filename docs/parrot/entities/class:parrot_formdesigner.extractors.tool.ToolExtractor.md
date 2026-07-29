---
type: Wiki Entity
title: ToolExtractor
id: class:parrot_formdesigner.extractors.tool.ToolExtractor
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extracts FormSchema from AbstractTool.args_schema.
---

# ToolExtractor

Defined in [`parrot_formdesigner.extractors.tool`](../summaries/mod:parrot_formdesigner.extractors.tool.md).

```python
class ToolExtractor
```

Extracts FormSchema from AbstractTool.args_schema.

Delegates Pydantic model introspection to PydanticExtractor, then
applies tool-specific metadata and field filtering:
- Excludes context fields (AbstractToolArgsSchema._context_fields)
- Excludes pre-filled known_values fields
- Sets form_id to "{tool.name}_form"
- Uses tool.description as form description

Example:
    extractor = ToolExtractor()
    schema = extractor.extract(my_tool, known_values={"user_id": "123"})

## Methods

- `def extract(self, tool: Any, *, exclude_fields: set[str] | None=None, known_values: dict[str, Any] | None=None) -> FormSchema` — Extract FormSchema from a tool's args_schema.
