---
type: Wiki Summary
title: parrot.skills.file_registry
id: mod:parrot.skills.file_registry
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Filesystem-based skill registry with eager loading.
relates_to:
- concept: class:parrot.skills.file_registry.SkillFileRegistry
  rel: defines
- concept: mod:parrot.skills.models
  rel: references
- concept: mod:parrot.skills.parsers
  rel: references
---

# `parrot.skills.file_registry`

Filesystem-based skill registry with eager loading.

Scans AGENTS_DIR/{agent_id}/skills/ (authored) and skills/learned/ (LLM-generated)
at configure time, discovers both single-file (``{name}.md``) and composite
(``{name}/SKILL.md``) skill layouts, validates, and indexes by trigger name.

## Classes

- **`SkillFileRegistry`** — Filesystem-based skill registry with eager loading.
