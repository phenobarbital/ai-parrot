---
type: Wiki Overview
title: 'TASK-1088: Concept Catalog Service'
id: doc:sdd-tasks-completed-task-1088-concept-catalog-service-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The `ConceptCatalogService` is the sole SQL writer for the concept catalog
  tables (`ontology_concept`, `ontology_concept_isa`, `ontology_concept_audit`, `ontology_concept_outbox`).
  It implements the five-state machine, synonym collision detection, is_a DAG cycle
  detection, audit '
relates_to:
- concept: mod:parrot.knowledge.ontology.concept_catalog.models
  rel: mentions
- concept: mod:parrot.knowledge.ontology.concept_catalog.service
  rel: mentions
- concept: mod:parrot.knowledge.ontology.exceptions
  rel: mentions
---

# TASK-1088: Concept Catalog Service

**Feature**: FEAT-159 — Topic-Authority Ontology Curation
**Spec**: `sdd/specs/topic-authority-ontology.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-1084, TASK-1085, TASK-1087
**Assigned-to**: unassigned

---

## Context

The `ConceptCatalogService` is the sole SQL writer for the concept catalog tables (`ontology_concept`, `ontology_concept_isa`, `ontology_concept_audit`, `ontology_concept_outbox`). It implements the five-state machine, synonym collision detection, is_a DAG cycle detection, audit trail, outbox enqueue, and cascade alerts on deprecation. This is the largest and most critical module in the feature. See spec §3 Module 4.

---

## Scope

- Implement `ConceptCatalogService` with all methods listed in spec §2 "New Public Interfaces".
- Five-state machine: proposed → pending_review → approved → deprecated/rejected. Restore path: deprecated → proposed.
- Transactional discipline: row lock → validate → UPDATE → audit INSERT → outbox INSERT, all in one transaction.
- Cycle detection on `propose_isa_edge` and `approve` for is_a edges (DFS or networkx).
- Synonym collision check on `propose_concept`.
- `CascadeAlert` emission on concept deprecation.
- Framework concept immutability: `propose_isa_edge` with `parent_tier="tenant"` targeting a framework concept raises error.
- Write comprehensive unit tests.

**NOT in scope**: Outbox draining (TASK-1089), HTTP routes (TASK-1092), YAML seeding (TASK-1090), reconciliation (TASK-1091).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/service.py` | CREATE | ConceptCatalogService |
| `tests/knowledge/ontology/concept_catalog/test_service.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.ontology.concept_catalog.models import (
    ConceptRow,        # TASK-1087
    IsaEdgeRow,        # TASK-1087
    CascadeAlert,      # TASK-1087
)
from parrot.knowledge.ontology.exceptions import (
    OntologyError,            # exceptions.py:4
    CycleError,               # TASK-1085
    SynonymConflictError,     # TASK-1085
)
# asyncdb / asyncpg for Postgres — verify exact import pattern used in project
# networkx for cycle detection (already in pyproject.toml as networkx>=3.0)
import networkx as nx
```

### Existing Signatures to Use

```python
# No existing service to extend — this is a new class.
# Pattern reference: FEAT-topic-authority-operational service shape
# (not yet implemented — follow spec §7 patterns).
```

### Does NOT Exist

- ~~`ConceptCatalogService`~~ — does not exist; this task creates it.
- ~~`TopicAuthorityService`~~ — exists only in FEAT-topic-authority-operational brainstorm; not yet implemented. Follow the same transactional pattern described in spec §7.
- ~~`topic_authority` Postgres table~~ — not yet implemented. Cascade notification reads from it; for now, return empty `CascadeAlert` or skip cascade if table doesn't exist.
- ~~`InvalidTransitionError`~~ — not in the exceptions module. Define state-machine validation inline or add a local exception.

---

## Implementation Notes

### Pattern to Follow

```python
class ConceptCatalogService:
    """Operational truth for per-tenant Concept entities and is_a edges."""

    def __init__(self, pg_pool) -> None:
        self.logger = logging.getLogger("Parrot.Ontology.ConceptCatalog")
        self._pool = pg_pool

    async def propose_concept(self, tenant_id: str, slug: str, label: str,
                               asserted_by: str, ...) -> UUID:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # 1. Check synonym collision
                # 2. INSERT ontology_concept (state='proposed')
                # 3. INSERT audit row
                # 4. INSERT outbox row
                return concept_id

    async def approve(self, target_id: UUID, target_kind: str,
                      actor: str, reason: str | None = None) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # 1. SELECT ... FOR UPDATE
                # 2. Validate transition (must be proposed or pending_review)
                # 3. If target_kind == 'isa_edge': run cycle detection
                # 4. UPDATE state → approved
                # 5. INSERT audit
                # 6. INSERT outbox
```

### Key Constraints

- **State machine valid transitions**:
  - proposed → pending_review, approved, rejected
  - pending_review → approved, rejected
  - approved → deprecated
  - deprecated → proposed (restore)
  - rejected → proposed (restore)
- **Cycle detection**: Build a directed graph of all approved + pending is_a edges for the tenant, add the candidate edge, check for cycles. Use `networkx.DiGraph` + `networkx.find_cycle()` or hand-rolled DFS.
- **Synonym collision**: Before inserting a concept, query `ontology_concept` for any approved concept in the same tenant whose `synonyms` array overlaps with the new concept's synonyms. Use `SELECT ... WHERE state = 'approved' AND synonyms && ARRAY[...]`.
- **Framework is_a guard**: `propose_isa_edge` with `parent_tier="framework"` is allowed (tenant → framework). But the reverse (framework pointing to tenant) is blocked.
- **Cascade on deprecate**: When deprecating a concept, query operational `topic_authority` table for edges referencing this concept. Return a `CascadeAlert` with affected edge IDs. If the operational table doesn't exist yet (FEAT-topic-authority-operational not landed), return `None`.
- **Audit diff**: JSONB with `{before: {...}, after: {...}}` capturing the changed fields.
- **Outbox operations**: `publish_to_graph` (on approve), `deprecate_in_graph` (on deprecate), `invalidate_cache` (on any state change).

### References in Codebase

- Spec §2 "New Public Interfaces" — full method signatures.
- Spec §7 "Patterns to Follow" — transactional discipline pattern.

---

## Acceptance Criteria

- [ ] `propose_concept` creates row with state='proposed', writes audit + outbox.
- [ ] `approve` only succeeds from proposed/pending_review states.
- [ ] `approve` on rejected concept raises state-machine error.
- [ ] Synonym collision detected: `SynonymConflictError` raised.
- [ ] Unique constraint: two concurrent proposes for same (tenant, slug) yield exactly one success.
- [ ] `propose_isa_edge` with cycle raises `CycleError` at propose time.
- [ ] Cross-tier: tenant→framework succeeds; framework→tenant blocked.
- [ ] `deprecate` emits `CascadeAlert` with affected edge IDs.
- [ ] `modify_metadata` cannot change slug/label after approve.
- [ ] `get_live_concepts` returns only approved concepts for the tenant.
- [ ] `get_isa_subgraph` returns ancestor/descendant tree.
- [ ] `get_history` returns audit trail ordered by occurred_at DESC.
- [ ] All tests pass: `pytest tests/knowledge/ontology/concept_catalog/test_service.py -v`

---

## Test Specification

```python
# tests/knowledge/ontology/concept_catalog/test_service.py
import pytest
from uuid import uuid4
from parrot.knowledge.ontology.concept_catalog.service import ConceptCatalogService
from parrot.knowledge.ontology.concept_catalog.models import ConceptRow, CascadeAlert
from parrot.knowledge.ontology.exceptions import CycleError, SynonymConflictError


class TestProposeConcept:
    async def test_creates_proposed_row(self, concept_service, empty_tenant):
        cid = await concept_service.propose_concept(
            tenant_id=empty_tenant, slug="sales_comp", label="Sales Compensation",
            asserted_by="curator@test.com",
        )
        assert cid is not None

    async def test_synonym_collision_rejected(self, concept_service, empty_tenant):
        await concept_service.propose_concept(
            tenant_id=empty_tenant, slug="sales", label="Sales",
            asserted_by="c", synonyms=["commissions"],
        )
        # approve it
        # then propose another with overlapping synonym
        with pytest.raises(SynonymConflictError):
            await concept_service.propose_concept(
                tenant_id=empty_tenant, slug="comp", label="Comp",
                asserted_by="c", synonyms=["commissions"],
            )


class TestStateMachine:
    async def test_approve_from_proposed(self, concept_service, empty_tenant):
        cid = await concept_service.propose_concept(...)
        await concept_service.approve(cid, "concept", "reviewer")
        # verify state is now approved

    async def test_approve_from_rejected_fails(self, concept_service, empty_tenant):
        cid = await concept_service.propose_concept(...)
        await concept_service.reject(cid, "concept", "reviewer")
        with pytest.raises(Exception):  # InvalidTransitionError
            await concept_service.approve(cid, "concept", "reviewer")


class TestIsaEdge:
    async def test_cycle_detection(self, concept_service, seeded_tenant):
        # A→B exists approved. Propose B→A → CycleError
        with pytest.raises(CycleError):
            await concept_service.propose_isa_edge(...)

    async def test_cross_tier_tenant_to_framework(self, concept_service, empty_tenant):
        cid = await concept_service.propose_concept(...)
        eid = await concept_service.propose_isa_edge(
            tenant_id=empty_tenant, child_id=cid,
            parent_tier="framework", parent_ref="Employee",
            asserted_by="c",
        )
        assert eid is not None


class TestDeprecate:
    async def test_emits_cascade_alert(self, concept_service, seeded_tenant):
        alert = await concept_service.deprecate(concept_id, "concept", "admin")
        assert isinstance(alert, CascadeAlert) or alert is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §2 and §3 Module 4 for full API and transactional pattern
2. **Verify** TASK-1084 (migration), TASK-1085 (exceptions), TASK-1087 (models) are done
3. **Check** asyncdb/asyncpg usage patterns in the project for connection pool handling
4. **Implement** the service with full transactional discipline
5. **Run tests**: `pytest tests/knowledge/ontology/concept_catalog/test_service.py -v`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
