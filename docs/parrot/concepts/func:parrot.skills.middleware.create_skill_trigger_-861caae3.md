---
type: Concept
title: create_skill_trigger_middleware()
id: func:parrot.skills.middleware.create_skill_trigger_middleware
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Create a PromptMiddleware that detects /trigger patterns.
---

# create_skill_trigger_middleware

```python
def create_skill_trigger_middleware(registry: SkillFileRegistry, bot: 'AbstractBot', priority: int=-10) -> PromptMiddleware
```

Create a PromptMiddleware that detects /trigger patterns.

The middleware intercepts user messages starting with ``/``, looks up the
trigger in the registry, and if found:
- Sets ``bot._active_skill`` to the matching SkillDefinition
- Returns the remaining text after the trigger

Reserved triggers ``/skills`` and ``/help`` return a formatted listing
of available skills.

Args:
    registry: The SkillFileRegistry to look up triggers in.
    bot: The bot instance — used to set ``_active_skill`` via closure.
    priority: Middleware priority (lower runs first). Default ``-10``.

Returns:
    A configured PromptMiddleware instance.
