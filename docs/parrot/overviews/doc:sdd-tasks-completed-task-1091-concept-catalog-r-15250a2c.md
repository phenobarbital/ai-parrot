---
type: Wiki Overview
title: 'TASK-1091: Concept Catalog Reconciliation Job'
id: doc:sdd-tasks-completed-task-1091-concept-catalog-reconciliation-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'A nightly reconciliation job that detects drift between Postgres (source
  of truth) and ArangoDB (materialized view). For each tenant: scan approved PG rows,
  verify matching ArangoDB documents/edges with correct `pg_concept_id`/`pg_isa_edge_id`,
  and reverse-scan. Discrepancies are'
relates_to:
- concept: mod:parrot.knowledge.ontology.concept_catalog.reconcile
  rel: mentions
- concept: mod:parrot.knowledge.ontology.graph_store
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
---

# TASK-1091: Concept Catalog Reconciliation Job

**Feature**: FEAT-159 — Topic-Authority Ontology Curation
**Spec**: `sdd/specs/topic-authority-ontology.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1088, TASK-1089
**Assigned-to**: unassigned

---

## Context

A nightly reconciliation job that detects drift between Postgres (source of truth) and ArangoDB (materialized view). For each tenant: scan approved PG rows, verify matching ArangoDB documents/edges with correct `pg_concept_id`/`pg_isa_edge_id`, and reverse-scan. Discrepancies are logged but NOT auto-repaired. See spec §3 Module 7.

---

## Scope

- Implement `ConceptCatalogReconciler` with `reconcile(tenant_id)` method.
- Forward scan: for each approved concept/edge in PG, check ArangoDB has matching document.
- Reverse scan: for each document in ArangoDB `concepts`/`concept_isa` collections, verify PG row exists and is approved.
- Log discrepancies with `self.logger.warning(...)`.
- Return a `ReconciliationReport` with counts and discrepancy details.
- Only flag rows whose `updated_at` is older than `outbox_drain_interval × 10` (ignore in-flight).
- Write unit tests.

**NOT in scope**: Auto-repair, alerting hookup (reuses existing infrastructure), scheduling.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/reconcile.py` | CREATE | ConceptCatalogReconciler |
| `tests/knowledge/ontology/concept_catalog/test_reconcile.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.ontology.graph_store import OntologyGraphStore  # graph_store.py:33
from parrot.knowledge.ontology.schema import TenantContext             # schema.py:261
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py
class OntologyGraphStore:
    async def get_all_nodes(
        self, ctx: TenantContext, collection: str,
    ) -> list[dict[str, Any]]: ...                                    # line 386
    async def upsert_nodes(...) -> UpsertResult: ...                  # line 225 (NOT used — no auto-repair)
```

### Does NOT Exist

- ~~`ConceptCatalogReconciler`~~ — does not exist; this task creates it.
- ~~Auto-repair logic~~ — explicitly forbidden by spec. Reconciler only reports.

---

## Implementation Notes

### Key Constraints

- **No auto-repair**: only log discrepancies, return report.
- **In-flight filter**: skip rows where `updated_at > now() - (outbox_drain_interval × 10)`.
- Compare by `pg_concept_id` attribute on ArangoDB documents.
- Log at WARNING level for each discrepancy.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py` — `get_all_nodes()` for reverse scan.
- Spec §7 "Known Risks / Gotchas" — false positive handling.

---

## Acceptance Criteria

- [ ] Forward scan detects PG rows missing from ArangoDB.
- [ ] Reverse scan detects ArangoDB docs missing from PG.
- [ ] In-flight rows (recent `updated_at`) are ignored.
- [ ] Discrepancies logged at WARNING level.
- [ ] No auto-repair — only reporting.
- [ ] Returns structured `ReconciliationReport`.
- [ ] All tests pass: `pytest tests/knowledge/ontology/concept_catalog/test_reconcile.py -v`

---

## Test Specification

```python
# tests/knowledge/ontology/concept_catalog/test_reconcile.py
import pytest
from parrot.knowledge.ontology.concept_catalog.reconcile import ConceptCatalogReconciler


class TestReconciliation:
    async def test_detects_missing_arango_doc(self, reconciler, pg_with_approved, empty_arango):
        report = await reconciler.reconcile("tenant-a")
        assert report.missing_in_arango > 0

    async def test_detects_orphan_arango_doc(self, reconciler, empty_pg, arango_with_docs):
        report = await reconciler.reconcile("tenant-a")
        assert report.orphans_in_arango > 0

    async def test_no_auto_repair(self, reconciler, pg_with_approved, empty_arango):
        await reconciler.reconcile("tenant-a")
        # verify ArangoDB still empty — no repair happened
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §3 Module 7 and §7 reconciliation posture
2. **Verify** TASK-1088 and TASK-1089 are done
3. **Read** `graph_store.py` `get_all_nodes()` for reverse scan pattern
4. **Implement** reconciler with no auto-repair
5. **Run tests**: `pytest tests/knowledge/ontology/concept_catalog/test_reconcile.py -v`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
