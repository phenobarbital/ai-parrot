---
type: Wiki Summary
title: parrot.knowledge.graphindex.extractors
id: mod:parrot.knowledge.graphindex.extractors
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: GraphIndex extractors sub-package.
relates_to:
- concept: mod:parrot.knowledge.graphindex.extractors.code
  rel: references
- concept: mod:parrot.knowledge.graphindex.extractors.loader
  rel: references
- concept: mod:parrot.knowledge.graphindex.extractors.odoo_code
  rel: references
- concept: mod:parrot.knowledge.graphindex.extractors.skill
  rel: references
---

# `parrot.knowledge.graphindex.extractors`

GraphIndex extractors sub-package.

Four parallel extractors feed UniversalNode/UniversalEdge instances
into the pipeline:

- ``code.CodeExtractor``         — tree-sitter Python parsing
- ``odoo_code.OdooCodeExtractor`` — Odoo-aware extension of CodeExtractor (FEAT-240)
- ``loader.LoaderExtractor``     — ai-parrot-loaders + PageIndex integration
- ``skill.SkillExtractor``       — SKILL.md frontmatter parsing
