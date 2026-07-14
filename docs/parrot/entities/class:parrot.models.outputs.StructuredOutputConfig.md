---
type: Wiki Entity
title: StructuredOutputConfig
id: class:parrot.models.outputs.StructuredOutputConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for structured output parsing.
---

# StructuredOutputConfig

Defined in [`parrot.models.outputs`](../summaries/mod:parrot.models.outputs.md).

```python
class StructuredOutputConfig
```

Configuration for structured output parsing.

## Methods

- `def get_schema(self) -> dict[str, Any]` — Extract JSON schema from output_type.
- `def format_schema_instruction(self) -> str` — Format the schema as an instruction for the system prompt.
