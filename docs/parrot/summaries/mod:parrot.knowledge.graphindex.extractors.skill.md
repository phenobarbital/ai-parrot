---
type: Wiki Summary
title: parrot.knowledge.graphindex.extractors.skill
id: mod:parrot.knowledge.graphindex.extractors.skill
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: SKILL.md extractor for GraphIndex.
relates_to:
- concept: class:parrot.knowledge.graphindex.extractors.skill.SkillExtractor
  rel: defines
- concept: mod:parrot.knowledge.graphindex.schema
  rel: references
---

# `parrot.knowledge.graphindex.extractors.skill`

SKILL.md extractor for GraphIndex.

Parses SKILL.md files (YAML frontmatter + markdown body) and emits
``UniversalNode`` instances with ``kind=NodeKind.SKILL``.  The ``title``
is derived from the frontmatter ``name`` field and ``summary`` from
``description``.  All other frontmatter fields are stored in
``domain_tags``.

## Classes

- **`SkillExtractor`** — Extract Skill nodes from SKILL.md files.
