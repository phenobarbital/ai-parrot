---
type: Wiki Summary
title: parrot.knowledge.ontology.concept_catalog.service
id: mod:parrot.knowledge.ontology.concept_catalog.service
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Concept Catalog Service — sole SQL writer for ontology_concept* tables.
relates_to:
- concept: class:parrot.knowledge.ontology.concept_catalog.service.ConceptCatalogService
  rel: defines
- concept: mod:parrot.knowledge.ontology.concept_catalog.models
  rel: references
- concept: mod:parrot.knowledge.ontology.exceptions
  rel: references
---

# `parrot.knowledge.ontology.concept_catalog.service`

Concept Catalog Service — sole SQL writer for ontology_concept* tables.

Implements the five-state machine for Concept entities and is_a edges.
All state-changing operations follow strict transactional discipline:
    1. SELECT ... FOR UPDATE row lock.
    2. Validate transition (state machine + invariants).
    3. UPDATE row.
    4. INSERT audit row.
    5. INSERT outbox row.
All within a single transaction.

## Classes

- **`ConceptCatalogService`** — Operational truth for per-tenant Concept entities and is_a edges.
