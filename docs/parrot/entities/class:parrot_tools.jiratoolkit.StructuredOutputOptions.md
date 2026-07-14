---
type: Wiki Entity
title: StructuredOutputOptions
id: class:parrot_tools.jiratoolkit.StructuredOutputOptions
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Options to shape the output of Jira items into either a whitelist or a Pydantic
  model.
---

# StructuredOutputOptions

Defined in [`parrot_tools.jiratoolkit`](../summaries/mod:parrot_tools.jiratoolkit.md).

```python
class StructuredOutputOptions(BaseModel)
```

Options to shape the output of Jira items into either a whitelist or a Pydantic model.


You can:
- provide `include` as a list of dot-paths to keep (e.g., ["key", "fields.summary", "fields.assignee.displayName"]).
- OR provide `mapping` as {dest_key: dot_path} to rename/flatten fields.
- OR provide `model_path` as a dotted import path to a BaseModel subclass. We will validate and return `model_dump()`.


If more than one is provided, precedence is: mapping > include > model_path (mapping/include are applied before model).
