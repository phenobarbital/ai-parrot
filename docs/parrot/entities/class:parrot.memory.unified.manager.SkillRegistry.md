---
type: Wiki Entity
title: SkillRegistry
id: class:parrot.memory.unified.manager.SkillRegistry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Structural protocol for skill registries.
---

# SkillRegistry

Defined in [`parrot.memory.unified.manager`](../summaries/mod:parrot.memory.unified.manager.md).

```python
class SkillRegistry(Protocol)
```

Structural protocol for skill registries.

Any object that implements ``get_relevant_skills`` satisfies this
protocol without explicit inheritance.

## Methods

- `async def get_relevant_skills(self, query: str, max_skills: int=3) -> str` — Return relevant skill descriptions for *query* as formatted text.
- `async def configure(self, **kwargs: Any) -> None` — Optional lifecycle hook — initialise the registry.
- `async def cleanup(self) -> None` — Optional lifecycle hook — release resources.
