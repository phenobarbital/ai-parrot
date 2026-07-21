---
type: Wiki Summary
title: parrot.skills.middleware
id: mod:parrot.skills.middleware
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Skill trigger middleware for the prompt pipeline.
relates_to:
- concept: func:parrot.skills.middleware.create_skill_trigger_middleware
  rel: defines
- concept: mod:parrot.bots.middleware
  rel: references
- concept: mod:parrot.skills.file_registry
  rel: references
---

# `parrot.skills.middleware`

Skill trigger middleware for the prompt pipeline.

Factory function that creates a PromptMiddleware detecting /trigger patterns
at the start of user messages, stripping the prefix, setting the activated
SkillDefinition on the bot instance, and handling reserved /skills and /help
triggers.

## Functions

- `def create_skill_trigger_middleware(registry: SkillFileRegistry, bot: 'AbstractBot', priority: int=-10) -> PromptMiddleware` — Create a PromptMiddleware that detects /trigger patterns.
