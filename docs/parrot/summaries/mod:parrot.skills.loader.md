---
type: Wiki Summary
title: parrot.skills.loader
id: mod:parrot.skills.loader
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: SkillsDirectoryLoader — Filesystem discovery for skills.
relates_to:
- concept: class:parrot.skills.loader.SkillsDirectoryLoader
  rel: defines
- concept: mod:parrot.skills.file_registry
  rel: references
- concept: mod:parrot.skills.models
  rel: references
- concept: mod:parrot.skills.parsers
  rel: references
---

# `parrot.skills.loader`

SkillsDirectoryLoader — Filesystem discovery for skills.

Scans configured filesystem paths to discover both single-file (``.md``)
and composite (``dir/SKILL.md``) skill layouts. Discovered skills are
hot-added to a :class:`~parrot.skills.file_registry.SkillFileRegistry`
via :meth:`load_into`.

Boot-time usage::

    loader = SkillsDirectoryLoader(paths=[Path(".agent/skills/")])
    count = await loader.load_into(registry)

## Classes

- **`SkillsDirectoryLoader`** — Discover and load skills from one or more filesystem directories.
