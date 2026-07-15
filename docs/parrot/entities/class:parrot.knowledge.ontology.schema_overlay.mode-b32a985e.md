---
type: Wiki Entity
title: SchemaOverlayRow
id: class:parrot.knowledge.ontology.schema_overlay.models.SchemaOverlayRow
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Represents a row in the ontology_schema_overlay Postgres table.
---

# SchemaOverlayRow

Defined in [`parrot.knowledge.ontology.schema_overlay.models`](../summaries/mod:parrot.knowledge.ontology.schema_overlay.models.md).

```python
class SchemaOverlayRow(BaseModel)
```

Represents a row in the ontology_schema_overlay Postgres table.

Schema overlays extend the tenant's merged ontology with new entity types,
relation types, or traversal patterns. A mandatory dry-run gate validates
the overlay before it can be approved.

Attributes:
    id: UUID primary key.
    tenant_id: Tenant owning this overlay.
    overlay_kind: Type of overlay — entity_type, relation_type, or traversal_pattern.
    name: Name of the entity/relation/pattern being introduced.
    definition: Serialized definition dict (EntityDef, RelationDef, or TraversalPattern).
    state: Current state in the five-state machine.
    asserted_by: Who asserted this overlay.
    reviewed_by: Reviewer (optional).
    rationale: Curator's rationale (optional).
    dry_run_report: Last dry-run outcome (success or failure + trace).
