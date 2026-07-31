---
type: Wiki Summary
title: parrot.knowledge.okf
id: mod:parrot.knowledge.okf
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Shared OKF (Open Knowledge Framework) core package.
relates_to:
- concept: mod:parrot.knowledge.okf.frontmatter
  rel: references
- concept: mod:parrot.knowledge.okf.ontology
  rel: references
- concept: mod:parrot.knowledge.okf.uri
  rel: references
- concept: mod:parrot.knowledge.okf.utils
  rel: references
---

# `parrot.knowledge.okf`

Shared OKF (Open Knowledge Framework) core package.

Provides the shared type vocabulary, frontmatter engine, URI scheme, and
filesystem utilities used by both PageIndex and GraphIndex.  This package
is the single source of truth for OKF types, replacing the previous
PageIndex-resident definitions.

Modules:
    ontology: ConceptType, RelationType, RelatesTo, SourceProvenance
    frontmatter: ConceptFrontmatter, project_frontmatter, parse_frontmatter
    uri: build_uri, parse_uri
    utils: flatten_concept_id_for_filename
