---
type: Wiki Entity
title: Skill
id: class:parrot.skills.models.Skill
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A versioned skill/knowledge document.
---

# Skill

Defined in [`parrot.skills.models`](../summaries/mod:parrot.skills.models.md).

```python
class Skill
```

A versioned skill/knowledge document.

Contains metadata + version history.
The actual content is stored in SkillVersion objects.

## Methods

- `def to_dict(self) -> Dict[str, Any]`
- `def from_dict(cls, data: Dict[str, Any]) -> 'Skill'`
- `def searchable_text(self) -> str` — Text for embedding generation.
