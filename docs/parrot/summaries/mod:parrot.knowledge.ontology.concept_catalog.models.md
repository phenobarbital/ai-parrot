---
type: Wiki Summary
title: parrot.knowledge.ontology.concept_catalog.models
id: mod:parrot.knowledge.ontology.concept_catalog.models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pydantic v2 row models for the Concept Catalog tables.
relates_to:
- concept: class:parrot.knowledge.ontology.concept_catalog.models.CascadeAlert
  rel: defines
- concept: class:parrot.knowledge.ontology.concept_catalog.models.ConceptRow
  rel: defines
- concept: class:parrot.knowledge.ontology.concept_catalog.models.IsaEdgeRow
  rel: defines
---

# `parrot.knowledge.ontology.concept_catalog.models`

Pydantic v2 row models for the Concept Catalog tables.

These models represent the Postgres rows for ontology_concept,
ontology_concept_isa, and the CascadeAlert notification type emitted
when a Concept is deprecated. They are used by the service, worker,
seed, reconcile, and HTTP modules.

## Classes

- **`ConceptRow(BaseModel)`** — Represents a row in the ontology_concept Postgres table.
- **`IsaEdgeRow(BaseModel)`** — Represents a row in the ontology_concept_isa Postgres table.
- **`CascadeAlert(BaseModel)`** — Notification emitted to the operational service when a Concept is deprecated.
