---
type: Wiki Summary
title: parrot.knowledge.pageindex.okf.frontmatter
id: mod:parrot.knowledge.pageindex.okf.frontmatter
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Backwards-compatible re-export shim for OKF frontmatter engine.
relates_to:
- concept: mod:parrot.knowledge.okf.frontmatter
  rel: references
---

# `parrot.knowledge.pageindex.okf.frontmatter`

Backwards-compatible re-export shim for OKF frontmatter engine.

The canonical definitions have moved to ``parrot.knowledge.okf.frontmatter``
(FEAT-239).  This module re-exports everything so that existing import paths:

    from parrot.knowledge.pageindex.okf.frontmatter import ConceptFrontmatter
    from parrot.knowledge.pageindex.okf.frontmatter import project_frontmatter
    from parrot.knowledge.pageindex.okf import ConceptFrontmatter

continue to work without modification.
