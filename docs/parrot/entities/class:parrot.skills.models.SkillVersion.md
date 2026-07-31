---
type: Wiki Entity
title: SkillVersion
id: class:parrot.skills.models.SkillVersion
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single immutable version of a skill.
---

# SkillVersion

Defined in [`parrot.skills.models`](../summaries/mod:parrot.skills.models.md).

```python
class SkillVersion
```

A single immutable version of a skill.

Version 0: stores full content
Version 1+: stores unified diff against previous version

## Methods

- `def to_dict(self) -> Dict[str, Any]`
- `def from_dict(cls, data: Dict[str, Any]) -> 'SkillVersion'`
