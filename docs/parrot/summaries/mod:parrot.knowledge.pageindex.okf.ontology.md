---
type: Wiki Summary
title: parrot.knowledge.pageindex.okf.ontology
id: mod:parrot.knowledge.pageindex.okf.ontology
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Backwards-compatible re-export shim for OKF ontology types.
relates_to:
- concept: mod:parrot.knowledge.okf.ontology
  rel: references
---

# `parrot.knowledge.pageindex.okf.ontology`

Backwards-compatible re-export shim for OKF ontology types.

The canonical definitions have moved to ``parrot.knowledge.okf.ontology``
(FEAT-239).  This module re-exports everything so that existing import paths:

    from parrot.knowledge.pageindex.okf.ontology import ConceptType
    from parrot.knowledge.pageindex.okf import ConceptType

continue to work without modification.
