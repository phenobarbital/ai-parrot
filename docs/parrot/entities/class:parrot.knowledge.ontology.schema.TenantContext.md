---
type: Wiki Entity
title: TenantContext
id: class:parrot.knowledge.ontology.schema.TenantContext
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Runtime context for a specific tenant.
---

# TenantContext

Defined in [`parrot.knowledge.ontology.schema`](../summaries/mod:parrot.knowledge.ontology.schema.md).

```python
class TenantContext(BaseModel)
```

Runtime context for a specific tenant.

Created by TenantOntologyManager and passed through the entire pipeline.

Args:
    tenant_id: Unique tenant identifier.
    arango_db: ArangoDB database name for this tenant.
    pgvector_schema: PgVector schema name for this tenant.
    ontology: The fully merged ontology for this tenant.
