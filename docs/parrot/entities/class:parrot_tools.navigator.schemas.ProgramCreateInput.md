---
type: Wiki Entity
title: ProgramCreateInput
id: class:parrot_tools.navigator.schemas.ProgramCreateInput
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Input for creating a new Navigator program.
---

# ProgramCreateInput

Defined in [`parrot_tools.navigator.schemas`](../summaries/mod:parrot_tools.navigator.schemas.md).

```python
class ProgramCreateInput(BaseModel)
```

Input for creating a new Navigator program.

## Methods

- `def clean_slug(cls, v: str) -> str`
- `def ensure_superuser(cls, v: List[int]) -> List[int]`
