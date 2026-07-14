---
type: Wiki Summary
title: parrot.knowledge.ontology.merger
id: mod:parrot.knowledge.ontology.merger
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Multi-layer YAML ontology composition engine.
relates_to:
- concept: class:parrot.knowledge.ontology.merger.OntologyMerger
  rel: defines
- concept: mod:parrot.knowledge.ontology.exceptions
  rel: references
- concept: mod:parrot.knowledge.ontology.parser
  rel: references
- concept: mod:parrot.knowledge.ontology.schema
  rel: references
---

# `parrot.knowledge.ontology.merger`

Multi-layer YAML ontology composition engine.

Merges base → domain → client ontology layers into a single MergedOntology
with deterministic rules for entity extension, relation concatenation, and
traversal pattern overrides.

## Classes

- **`OntologyMerger`** — Merge multiple ontology YAML layers into a single MergedOntology.
