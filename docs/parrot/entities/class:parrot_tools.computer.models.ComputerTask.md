---
type: Wiki Entity
title: ComputerTask
id: class:parrot_tools.computer.models.ComputerTask
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A reusable sequence of natural-language instructions.
---

# ComputerTask

Defined in [`parrot_tools.computer.models`](../summaries/mod:parrot_tools.computer.models.md).

```python
class ComputerTask(BaseModel)
```

A reusable sequence of natural-language instructions.

Tasks are named, described, and composed of ordered natural-language
steps. They can be parameterised for use inside run_loop().

Attributes:
    name: Unique task name (used as a key in the toolkit's task store).
    description: Human-readable description of the task's purpose.
    steps: Ordered list of natural-language instructions for the model.
    params_schema: Optional JSON Schema dict for validating params passed
        at runtime (e.g. when iterating over a list of records).
