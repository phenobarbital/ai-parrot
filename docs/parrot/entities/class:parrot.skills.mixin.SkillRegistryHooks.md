---
type: Wiki Entity
title: SkillRegistryHooks
id: class:parrot.skills.mixin.SkillRegistryHooks
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Hook functions for skill registry integration.
---

# SkillRegistryHooks

Defined in [`parrot.skills.mixin`](../summaries/mod:parrot.skills.mixin.md).

```python
class SkillRegistryHooks
```

Hook functions for skill registry integration.

## Methods

- `async def pre_ask_hook(agent: SkillRegistryMixin, query: str, **kwargs) -> Dict[str, Any]` — Get relevant skills before ask().
- `async def post_ask_hook(agent: SkillRegistryMixin, query: str, response: Any, **kwargs) -> None` — Optionally extract skills after ask().
