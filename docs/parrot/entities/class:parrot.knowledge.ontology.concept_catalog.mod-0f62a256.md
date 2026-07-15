---
type: Wiki Entity
title: CascadeAlert
id: class:parrot.knowledge.ontology.concept_catalog.models.CascadeAlert
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Notification emitted to the operational service when a Concept is deprecated.
---

# CascadeAlert

Defined in [`parrot.knowledge.ontology.concept_catalog.models`](../summaries/mod:parrot.knowledge.ontology.concept_catalog.models.md).

```python
class CascadeAlert(BaseModel)
```

Notification emitted to the operational service when a Concept is deprecated.

The cascade-on-deprecate flow emits exactly one CascadeAlert per
deprecation operation, listing all operational topic_authority edge IDs
that reference the deprecated concept.

Attributes:
    tenant_id: Tenant owning the deprecated concept.
    concept_id: UUID of the deprecated concept.
    concept_slug: Slug of the deprecated concept.
    affected_edge_ids: List of operational topic_authority.id values
        that reference this concept.
    notified_at: Timestamp when this alert was emitted.
