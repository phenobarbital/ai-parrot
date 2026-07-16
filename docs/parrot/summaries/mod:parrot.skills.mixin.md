---
type: Wiki Summary
title: parrot.skills.mixin
id: mod:parrot.skills.mixin
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: SkillRegistryMixin for AbstractBot integration.
relates_to:
- concept: class:parrot.skills.mixin.SkillRegistryHooks
  rel: defines
- concept: class:parrot.skills.mixin.SkillRegistryMixin
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.skills.file_registry
  rel: references
- concept: mod:parrot.skills.loader
  rel: references
- concept: mod:parrot.skills.middleware
  rel: references
- concept: mod:parrot.skills.models
  rel: references
- concept: mod:parrot.skills.parsers
  rel: references
- concept: mod:parrot.skills.prompt
  rel: references
- concept: mod:parrot.skills.store
  rel: references
- concept: mod:parrot.skills.tools
  rel: references
---

# `parrot.skills.mixin`

SkillRegistryMixin for AbstractBot integration.

Provides automatic skill management integration:
- Skill tools exposed to agent
- Context injection of relevant skills
- Auto-extraction of skills from conversations
- File-based skill registry with eager loading
- Skill trigger middleware for /trigger patterns
- Directory-based skill discovery (FEAT-188)
- Static <available_skills> prompt layer injection (FEAT-188)
- On-demand SkillFileToolkit registration (FEAT-188)

## Classes

- **`SkillRegistryMixin`** — Mixin to add skill registry capabilities to AbstractBot.
- **`SkillRegistryHooks`** — Hook functions for skill registry integration.
