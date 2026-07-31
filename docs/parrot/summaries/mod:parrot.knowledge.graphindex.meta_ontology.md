---
type: Wiki Summary
title: parrot.knowledge.graphindex.meta_ontology
id: mod:parrot.knowledge.graphindex.meta_ontology
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Universal meta-ontology for GraphIndex.
relates_to:
- concept: func:parrot.knowledge.graphindex.meta_ontology.build_graphindex_ontology
  rel: defines
- concept: mod:parrot.knowledge.ontology.schema
  rel: references
---

# `parrot.knowledge.graphindex.meta_ontology`

Universal meta-ontology for GraphIndex.

Provides the programmatic ``MergedOntology``-compatible definition with:
- 6 entity types: document, section, symbol, concept, rationale, skill
- 6 relation types: contains, references, defines, mentions, explains, extends

These definitions are **additive** — they do not conflict with existing
tenant ontologies.  They are intended to be merged at tenant initialisation
time via ``OntologyMerger``.

## Functions

- `def build_graphindex_ontology() -> MergedOntology` — Return the universal GraphIndex meta-ontology as a ``MergedOntology``.
