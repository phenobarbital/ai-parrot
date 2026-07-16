---
type: Wiki Overview
title: 'TASK-1097: Schema Overlay HTTP Routes'
id: doc:sdd-tasks-completed-task-1097-schema-overlay-http-routes-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: aiohttp routes under `/api/ontology/schema/*` providing the REST API for
  schema overlay operations. All routes require `ontology_schema_admin` role. The
  dry-run endpoint lets admins preview validation results before approving. See spec
  §3 Module 13.
relates_to:
- concept: mod:parrot.knowledge.ontology.exceptions
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema_overlay.models
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema_overlay.service
  rel: mentions
---

# TASK-1097: Schema Overlay HTTP Routes

**Feature**: FEAT-159 — Topic-Authority Ontology Curation
**Spec**: `sdd/specs/topic-authority-ontology.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1095
**Assigned-to**: unassigned

---

## Context

aiohttp routes under `/api/ontology/schema/*` providing the REST API for schema overlay operations. All routes require `ontology_schema_admin` role. The dry-run endpoint lets admins preview validation results before approving. See spec §3 Module 13.

---

## Scope

- Implement aiohttp route handlers for all schema overlay endpoints from spec §2 HTTP routes table.
- Role enforcement: `ontology_schema_admin` required for ALL schema endpoints.
- Tenant scoping from auth session.
- Request/response validation via Pydantic models.
- Error mapping: `DryRunFailedError` → 422 with report in body, not found → 404.
- Write unit tests.

**NOT in scope**: Service logic (TASK-1095), concept routes (TASK-1092), nav-admin UI.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/schema_overlay/http.py` | CREATE | aiohttp routes |
| `tests/knowledge/ontology/schema_overlay/test_http.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.ontology.schema_overlay.service import SchemaOverlayService  # TASK-1095
from parrot.knowledge.ontology.schema_overlay.models import SchemaOverlayRow, DryRunReport  # TASK-1093
from parrot.knowledge.ontology.exceptions import DryRunFailedError  # TASK-1085
from aiohttp import web  # already a dependency
```

### Existing Signatures to Use

```python
# Check existing aiohttp route patterns in parrot/handlers/
# Check navigator-auth for role enforcement
```

### Does NOT Exist

- ~~`/api/ontology/schema/` routes~~ — do not exist; this task creates them.
- ~~`ontology_schema_admin` role~~ — must be added by TASK-1103.

---

## Implementation Notes

### Route Table (from spec §2)

| Method | Path | Role |
|---|---|---|
| GET | `/api/ontology/schema?tenant=&state=&kind=` | `ontology_schema_admin` |
| GET | `/api/ontology/schema/{id}` | `ontology_schema_admin` |
| GET | `/api/ontology/schema/{id}/dry-run` | `ontology_schema_admin` |
| POST | `/api/ontology/schema` | `ontology_schema_admin` |
| POST | `/api/ontology/schema/{id}/transitions/{action}` | `ontology_schema_admin` |
| GET | `/api/ontology/reconciliation/report` | `topic_admin` |

### Key Constraints

- ALL schema routes require `ontology_schema_admin` — no lower role can access.
- `topic_admin` calling schema endpoints receives 403.
- Dry-run GET endpoint runs the validator and returns the `DryRunReport` without changing state.
- Approve transition endpoint catches `DryRunFailedError` and returns 422 with `dry_run_report` in body.
- Reconciliation report route requires `topic_admin` role (different from schema admin).

### References in Codebase

- `packages/ai-parrot/src/parrot/handlers/` — existing handler patterns.
- TASK-1092 (concept HTTP) — same aiohttp patterns.

---

## Acceptance Criteria

- [ ] All 6 routes implemented per route table.
- [ ] `topic_admin` calling `/api/ontology/schema` receives 403.
- [ ] `ontology_schema_admin` can access all schema routes.
- [ ] Dry-run GET returns `DryRunReport` JSON.
- [ ] Approve failure returns 422 with `dry_run_report` in body.
- [ ] All tests pass: `pytest tests/knowledge/ontology/schema_overlay/test_http.py -v`

---

## Test Specification

```python
# tests/knowledge/ontology/schema_overlay/test_http.py
import pytest


class TestSchemaOverlayHTTPRoutes:
    async def test_list_overlays(self, client, auth_schema_admin):
        resp = await client.get("/api/ontology/schema", params={"state": "proposed"})
        assert resp.status == 200

    async def test_topic_admin_cannot_access(self, client, auth_topic_admin):
        resp = await client.get("/api/ontology/schema")
        assert resp.status == 403

    async def test_propose_overlay(self, client, auth_schema_admin):
        resp = await client.post("/api/ontology/schema", json={
            "overlay_kind": "entity_type", "name": "Project",
            "definition": {"collection": "projects"},
        })
        assert resp.status == 201

    async def test_dry_run_endpoint(self, client, auth_schema_admin, pending_overlay_id):
        resp = await client.get(f"/api/ontology/schema/{pending_overlay_id}/dry-run")
        assert resp.status == 200
        body = await resp.json()
        assert "ok" in body

    async def test_approve_dry_run_failure(self, client, auth_schema_admin, bad_overlay_id):
        resp = await client.post(f"/api/ontology/schema/{bad_overlay_id}/transitions/approve")
        assert resp.status == 422
        body = await resp.json()
        assert "dry_run_report" in body
```

---

## Agent Instructions

When you pick up this task:

1. **Read** existing handler patterns and TASK-1092 (concept HTTP) for consistency
2. **Verify** TASK-1095 (service) is done
3. **Implement** all routes with `ontology_schema_admin` enforcement
4. **Run tests**: `pytest tests/knowledge/ontology/schema_overlay/test_http.py -v`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
