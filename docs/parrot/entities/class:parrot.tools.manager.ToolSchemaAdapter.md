---
type: Wiki Entity
title: ToolSchemaAdapter
id: class:parrot.tools.manager.ToolSchemaAdapter
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Adapter class to convert tool schemas between different LLM provider formats.
---

# ToolSchemaAdapter

Defined in [`parrot.tools.manager`](../summaries/mod:parrot.tools.manager.md).

```python
class ToolSchemaAdapter
```

Adapter class to convert tool schemas between different LLM provider formats.

## Methods

- `def clean_schema_for_provider(schema: Dict[str, Any], provider: ToolFormat) -> Dict[str, Any]` — Clean and adapt tool schema for specific LLM provider requirements.
