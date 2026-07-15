---
type: Wiki Entity
title: ReconciliationReport
id: class:parrot.knowledge.ontology.concept_catalog.reconcile.ReconciliationReport
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Summary of one reconciliation run for a tenant.
---

# ReconciliationReport

Defined in [`parrot.knowledge.ontology.concept_catalog.reconcile`](../summaries/mod:parrot.knowledge.ontology.concept_catalog.reconcile.md).

```python
class ReconciliationReport
```

Summary of one reconciliation run for a tenant.

Attributes:
    tenant_id: Tenant that was reconciled.
    missing_in_arango: Count of approved PG concepts absent from ArangoDB.
    orphans_in_arango: Count of ArangoDB docs with no matching approved PG row.
    missing_isa_in_arango: Count of approved PG edges absent from ArangoDB.
    orphan_edges_in_arango: Count of ArangoDB edges with no matching PG row.
    discrepancies: Human-readable detail strings for each discrepancy.

## Methods

- `def has_discrepancies(self) -> bool` — Return True if any drift was detected.
