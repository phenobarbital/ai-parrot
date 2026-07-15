---
type: Wiki Summary
title: parrot.knowledge.ontology.schema_overlay.http
id: mod:parrot.knowledge.ontology.schema_overlay.http
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Schema Overlay HTTP Routes (FEAT-159 TASK-1097).
relates_to:
- concept: func:parrot.knowledge.ontology.schema_overlay.http.dry_run_overlay_endpoint
  rel: defines
- concept: func:parrot.knowledge.ontology.schema_overlay.http.get_overlay
  rel: defines
- concept: func:parrot.knowledge.ontology.schema_overlay.http.list_overlays
  rel: defines
- concept: func:parrot.knowledge.ontology.schema_overlay.http.overlay_transition
  rel: defines
- concept: func:parrot.knowledge.ontology.schema_overlay.http.propose_overlay
  rel: defines
- concept: func:parrot.knowledge.ontology.schema_overlay.http.register_routes
  rel: defines
- concept: mod:parrot.knowledge.ontology.exceptions
  rel: references
- concept: mod:parrot.knowledge.ontology.schema_overlay.service
  rel: references
- concept: mod:parrot.knowledge.ontology.schema_overlay.validator
  rel: references
---

# `parrot.knowledge.ontology.schema_overlay.http`

Schema Overlay HTTP Routes (FEAT-159 TASK-1097).

Provides REST API endpoints under ``/api/ontology/schema/*`` for schema overlay
operations.  All routes require the ``ontology_schema_admin`` role.

Error mapping:
- ``DryRunFailedError`` → 422 with ``dry_run_report`` in body.
- ``InvalidTransitionError`` → 422 Unprocessable Entity.
- ``KeyError`` → 404 Not Found.
- Other exceptions → 500 Internal Server Error.

## Functions

- `async def list_overlays(request: web.Request) -> web.Response` — GET /api/ontology/schema — list pending overlays for tenant.
- `async def get_overlay(request: web.Request) -> web.Response` — GET /api/ontology/schema/{id}
- `async def dry_run_overlay_endpoint(request: web.Request) -> web.Response` — GET /api/ontology/schema/{id}/dry-run — run validation without approving.
- `async def propose_overlay(request: web.Request) -> web.Response` — POST /api/ontology/schema — propose a new schema overlay.
- `async def overlay_transition(request: web.Request) -> web.Response` — POST /api/ontology/schema/{id}/transitions/{action}
- `def register_routes(app: web.Application, prefix: str='/api/ontology') -> None` — Register all schema overlay routes on *app*.
