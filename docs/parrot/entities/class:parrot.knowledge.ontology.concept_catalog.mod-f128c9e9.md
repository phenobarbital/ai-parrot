---
type: Wiki Entity
title: IsaEdgeRow
id: class:parrot.knowledge.ontology.concept_catalog.models.IsaEdgeRow
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Represents a row in the ontology_concept_isa Postgres table.
---

# IsaEdgeRow

Defined in [`parrot.knowledge.ontology.concept_catalog.models`](../summaries/mod:parrot.knowledge.ontology.concept_catalog.models.md).

```python
class IsaEdgeRow(BaseModel)
```

Represents a row in the ontology_concept_isa Postgres table.

Captures a directional is_a (sub-class) relationship between a tenant
concept (child) and a parent concept that may live in the framework
layer or in the tenant's own catalog.

Attributes:
    id: UUID primary key.
    tenant_id: Tenant owning this edge.
    child_id: FK to ontology_concept.id (the sub-concept).
    parent_tier: Whether the parent lives in the framework or tenant layer.
    parent_ref: Framework concept name or tenant ontology_concept.id (as str).
    state: Current state in the five-state machine.
    asserted_by: Who asserted this edge.
    reviewed_by: Reviewer (optional).
    rationale: Curator's rationale (optional).
