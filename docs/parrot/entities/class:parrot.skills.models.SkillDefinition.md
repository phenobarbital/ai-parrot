---
type: Wiki Entity
title: SkillDefinition
id: class:parrot.skills.models.SkillDefinition
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parsed skill from a .md file with YAML frontmatter.
---

# SkillDefinition

Defined in [`parrot.skills.models`](../summaries/mod:parrot.skills.models.md).

```python
class SkillDefinition(BaseModel)
```

Parsed skill from a .md file with YAML frontmatter.

Represents a lightweight behavioral instruction that activates
on demand via deterministic /trigger patterns.

## Methods

- `def validate_token_count(cls, v: int) -> int` — Reject skills whose body exceeds the token limit.
