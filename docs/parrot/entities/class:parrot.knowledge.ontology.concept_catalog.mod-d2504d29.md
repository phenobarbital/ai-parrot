---
type: Wiki Entity
title: ConceptRow
id: class:parrot.knowledge.ontology.concept_catalog.models.ConceptRow
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Represents a row in the ontology_concept Postgres table.
---

# ConceptRow

Defined in [`parrot.knowledge.ontology.concept_catalog.models`](../summaries/mod:parrot.knowledge.ontology.concept_catalog.models.md).

```python
class ConceptRow(BaseModel)
```

Represents a row in the ontology_concept Postgres table.

Attributes:
    id: UUID primary key.
    tenant_id: Tenant owning this concept.
    slug: Tenant-local slug identifier (e.g. "sales_commissions").
    label: Human-readable display label.
    synonyms: List of synonym strings for this concept.
    description: Optional prose description.
    domain: Optional domain tag (e.g. "finance").
    state: Current state in the five-state machine.
    asserted_by: Who asserted this concept (user email or system).
    reviewed_by: Who reviewed the transition (optional).
    reviewed_at: When the review happened (optional).
    rationale: Curator's rationale for the proposal or decision.
    effective_from: When this concept became effective.
    effective_to: When this concept expires (optional).
