---
type: Wiki Entity
title: InfographicTemplate
id: class:parrot.models.infographic_templates.InfographicTemplate
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Defines the structure and block order for an infographic layout.
---

# InfographicTemplate

Defined in [`parrot.models.infographic_templates`](../summaries/mod:parrot.models.infographic_templates.md).

```python
class InfographicTemplate(BaseModel)
```

Defines the structure and block order for an infographic layout.

## Methods

- `def to_prompt_instruction(self) -> str` — Generate LLM prompt instructions from this template.
