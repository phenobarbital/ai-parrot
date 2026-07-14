---
type: Wiki Summary
title: parrot.knowledge.ontology.concept_catalog.reconcile
id: mod:parrot.knowledge.ontology.concept_catalog.reconcile
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Concept Catalog Reconciliation Job (FEAT-159 TASK-1091).
relates_to:
- concept: class:parrot.knowledge.ontology.concept_catalog.reconcile.ConceptCatalogReconciler
  rel: defines
- concept: class:parrot.knowledge.ontology.concept_catalog.reconcile.ReconciliationReport
  rel: defines
- concept: mod:parrot.knowledge.ontology.concept_catalog
  rel: references
- concept: mod:parrot.knowledge.ontology.graph_store
  rel: references
- concept: mod:parrot.knowledge.ontology.schema
  rel: references
---

# `parrot.knowledge.ontology.concept_catalog.reconcile`

Concept Catalog Reconciliation Job (FEAT-159 TASK-1091).

Detects drift between Postgres (source of truth) and ArangoDB (materialized
view).  The reconciler is **read-only**: it reports discrepancies but does not
auto-repair them.

Drift categories
-----------------
* **missing_in_arango** — approved PG row has no matching ArangoDB document.
* **orphans_in_arango** — ArangoDB document has no corresponding approved PG
  row (or the PG row is deprecated/rejected).

In-flight rows (``updated_at > now() - outbox_drain_interval × 10``) are
excluded from forward-scan results to prevent false positives during outbox
processing.

## Classes

- **`ReconciliationReport`** — Summary of one reconciliation run for a tenant.
- **`ConceptCatalogReconciler`** — Detect drift between Postgres and ArangoDB for a tenant's concept catalog.
