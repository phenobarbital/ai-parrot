---
type: Wiki Summary
title: parrot.knowledge.pageindex.okf
id: mod:parrot.knowledge.pageindex.okf
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: OKF Knowledge Layer subpackage for PageIndex.
relates_to:
- concept: mod:parrot.knowledge.pageindex.okf.bundle
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.concept_id
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.frontmatter
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.graph
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.lint
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.migrate
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.ontology
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.projection
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.tools
  rel: references
---

# `parrot.knowledge.pageindex.okf`

OKF Knowledge Layer subpackage for PageIndex.

This subpackage implements the OKF-compatible knowledge layer over PageIndex
(FEAT-238). It provides:

- ``ontology``: Controlled type/relation vocabulary (ConceptType, RelationType)
  and Pydantic data models (RelatesTo, SourceProvenance).
- ``concept_id``: Deterministic slug generation and dedup (assign_concept_ids).
- ``frontmatter``: ConceptFrontmatter model and byte-deterministic projection.
- ``graph``: In-memory knowledge graph (KnowledgeGraph).
- ``projection``: Sidecar and index.md generation.
- ``lint``: Knowledge base lint engine (FEAT-216).
- ``bundle``: OKF v0.1 bundle export/import (FEAT-216).
- ``migrate``: okf-migrate command for retrofitting existing trees.
- ``tools``: Named read tools for type-scoped retrieval and traversal.
