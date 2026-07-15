---
type: Wiki Summary
title: parrot.knowledge.ontology.discovery
id: mod:parrot.knowledge.ontology.discovery
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Relation discovery engine for automatic edge creation.
relates_to:
- concept: class:parrot.knowledge.ontology.discovery.DiscoveryResult
  rel: defines
- concept: class:parrot.knowledge.ontology.discovery.DiscoveryStats
  rel: defines
- concept: class:parrot.knowledge.ontology.discovery.RelationDiscovery
  rel: defines
- concept: mod:parrot.knowledge.ontology.schema
  rel: references
---

# `parrot.knowledge.ontology.discovery`

Relation discovery engine for automatic edge creation.

Discovers relationships between entities using configurable strategies:
exact field matching, fuzzy string matching, AI-assisted resolution,
and composite multi-field scoring.

## Classes

- **`DiscoveryStats(BaseModel)`** — Statistics for a discovery run.
- **`DiscoveryResult(BaseModel)`** — Result of a relation discovery operation.
- **`RelationDiscovery`** — Discover and create relationships between entities in the graph.
