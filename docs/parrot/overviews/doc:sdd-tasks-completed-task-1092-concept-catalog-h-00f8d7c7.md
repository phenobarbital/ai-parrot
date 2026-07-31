---
type: Wiki Overview
title: 'TASK-1092: Concept Catalog HTTP Routes'
id: doc:sdd-tasks-completed-task-1092-concept-catalog-http-routes-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'aiohttp routes under `/api/ontology/concepts/*` providing the REST API for
  concept catalog operations. Role enforcement via `navigator-auth`: `topic_curator`
  for reads/proposals, `topic_reviewer` for approvals, `topic_admin` for deprecation/restore.
  See spec §3 Module 8.'
relates_to:
- concept: mod:parrot.knowledge.ontology.concept_catalog.models
  rel: mentions
- concept: mod:parrot.knowledge.ontology.concept_catalog.service
  rel: mentions
- concept: mod:parrot.knowledge.ontology.exceptions
  rel: mentions
---

# TASK-1092: Concept Catalog HTTP Routes

**Feature**: FEAT-159 — Topic-Authority Ontology Curation
**Spec**: `sdd/specs/topic-authority-ontology.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1088
**Assigned-to**: unassigned

---

## Context

aiohttp routes under `/api/ontology/concepts/*` providing the REST API for concept catalog operations. Role enforcement via `navigator-auth`: `topic_curator` for reads/proposals, `topic_reviewer` for approvals, `topic_admin` for deprecation/restore. See spec §3 Module 8.

---

## Scope

- Implement aiohttp route handlers for all concept catalog endpoints listed in spec §2 HTTP routes table.
- Role enforcement: `topic_curator+` for reads and proposals, `topic_reviewer+` for approve/reject, `topic_admin` for deprecate/restore.
- Tenant scoping from auth session — no cross-tenant access.
- Request/response validation via Pydantic models.
- Error mapping: `SynonymConflictError` → 409, `CycleError` → 422, state-machine errors → 422, not found → 404.
- Write unit tests.

**NOT in scope**: Service logic (TASK-1088), nav-admin UI, schema overlay routes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/http.py` | CREATE | aiohttp routes |
| `tests/knowledge/ontology/concept_catalog/test_http.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.ontology.concept_catalog.service import ConceptCatalogService  # TASK-1088
from parrot.knowledge.ontology.concept_catalog.models import ConceptRow, IsaEdgeRow  # TASK-1087
from parrot.knowledge.ontology.exceptions import (
    CycleError,              # TASK-1085
    SynonymConflictError,    # TASK-1085
)
from aiohttp import web  # already a dependency
```

### Existing Signatures to Use

```python
# Check existing aiohttp route patterns in the project:
# - parrot/handlers/ for route registration pattern
# - navigator-auth for role enforcement decorators/middleware
# Verify exact import paths before use.
```

### Does NOT Exist

- ~~`/api/ontology/concepts/` routes~~ — do not exist; this task creates them.
- ~~A shared aiohttp route registration helper for ontology~~ — check if one exists in `parrot/handlers/`; if not, follow existing handler patterns.

---

## Implementation Notes

### Route Table (from spec §2)

| Method | Path | Role |
|---|---|---|
| GET | `/api/ontology/concepts?tenant=&state=&domain=&limit=&offset=` | `topic_curator`+ |
| GET | `/api/ontology/concepts/{id}` | `topic_curator`+ |
| GET | `/api/ontology/concepts/{id}/history` | `topic_curator`+ |
| GET | `/api/ontology/concepts/{id}/isa` | `topic_curator`+ |
| POST | `/api/ontology/concepts` | `topic_curator`+ |
| POST | `/api/ontology/concepts/{id}/transitions/submit` | `topic_curator`+ |
| POST | `/api/ontology/concepts/{id}/transitions/approve` | `topic_reviewer`+ |
| POST | `/api/ontology/concepts/{id}/transitions/reject` | `topic_reviewer`+ |
| POST | `/api/ontology/concepts/{id}/transitions/deprecate` | `topic_admin` |
| POST | `/api/ontology/concepts/{id}/transitions/restore` | `topic_admin` |
| PATCH | `/api/ontology/concepts/{id}` | `topic_reviewer`+ |
| POST | `/api/ontology/concepts/isa` | `topic_curator`+ |
| POST | `/api/ontology/concepts/isa/{id}/transitions/{action}` | per action |

### Key Constraints

- Tenant ID must come from the auth session, not from query params (for writes). Reads may filter by tenant from session.
- `topic_curator` cannot call `/transitions/approve` — must receive 403.
- All responses use JSON serialization of Pydantic models.
- Pagination: `limit` (default 50, max 200) and `offset` (default 0).

### References in Codebase

- `packages/ai-parrot/src/parrot/handlers/` — existing aiohttp handler patterns.
- Check navigator-auth for role enforcement middleware/decorators.

---

## Acceptance Criteria

- [ ] All 13 routes implemented per the route table.
- [ ] `topic_curator` calling `/transitions/approve` receives 403.
- [ ] `topic_curator` calling `/transitions/deprecate` receives 403.
- [ ] Cross-tenant request returns 403 or filtered empty results.
- [ ] `SynonymConflictError` → 409 response.
- [ ] `CycleError` → 422 response.
- [ ] State-machine error → 422 response.
- [ ] Not-found concept → 404 response.
- [ ] Pagination works with `limit` and `offset`.
- [ ] All tests pass: `pytest tests/knowledge/ontology/concept_catalog/test_http.py -v`

---

## Test Specification

```python
# tests/knowledge/ontology/concept_catalog/test_http.py
import pytest
from aiohttp.test_utils import AioHTTPTestCase


class TestConceptHTTPRoutes:
    async def test_list_concepts(self, client, seeded_tenant):
        resp = await client.get("/api/ontology/concepts", params={"state": "approved"})
        assert resp.status == 200

    async def test_propose_concept(self, client, auth_curator):
        resp = await client.post("/api/ontology/concepts", json={
            "slug": "new_concept", "label": "New Concept",
        })
        assert resp.status == 201

    async def test_curator_cannot_approve(self, client, auth_curator, proposed_concept_id):
        resp = await client.post(f"/api/ontology/concepts/{proposed_concept_id}/transitions/approve")
        assert resp.status == 403

    async def test_reviewer_can_approve(self, client, auth_reviewer, proposed_concept_id):
        resp = await client.post(f"/api/ontology/concepts/{proposed_concept_id}/transitions/approve")
        assert resp.status == 200

    async def test_synonym_conflict_returns_409(self, client, auth_curator, approved_concept_with_synonym):
        resp = await client.post("/api/ontology/concepts", json={
            "slug": "conflict", "label": "Conflict", "synonyms": ["existing_synonym"],
        })
        assert resp.status == 409
```

---

## Agent Instructions

When you pick up this task:

1. **Read** existing aiohttp handler patterns in `packages/ai-parrot/src/parrot/handlers/`
2. **Read** navigator-auth role enforcement pattern
3. **Verify** TASK-1088 service is done
4. **Implement** all routes with proper role enforcement
5. **Run tests**: `pytest tests/knowledge/ontology/concept_catalog/test_http.py -v`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
