---
type: Wiki Summary
title: parrot.knowledge.ontology.concept_catalog.http
id: mod:parrot.knowledge.ontology.concept_catalog.http
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Concept Catalog HTTP Routes (FEAT-159 TASK-1092).
relates_to:
- concept: func:parrot.knowledge.ontology.concept_catalog.http.approve_concept
  rel: defines
- concept: func:parrot.knowledge.ontology.concept_catalog.http.deprecate_concept
  rel: defines
- concept: func:parrot.knowledge.ontology.concept_catalog.http.get_concept
  rel: defines
- concept: func:parrot.knowledge.ontology.concept_catalog.http.get_concept_history
  rel: defines
- concept: func:parrot.knowledge.ontology.concept_catalog.http.get_concept_isa
  rel: defines
- concept: func:parrot.knowledge.ontology.concept_catalog.http.isa_edge_transition
  rel: defines
- concept: func:parrot.knowledge.ontology.concept_catalog.http.list_concepts
  rel: defines
- concept: func:parrot.knowledge.ontology.concept_catalog.http.modify_concept
  rel: defines
- concept: func:parrot.knowledge.ontology.concept_catalog.http.propose_concept
  rel: defines
- concept: func:parrot.knowledge.ontology.concept_catalog.http.propose_isa_edge
  rel: defines
- concept: func:parrot.knowledge.ontology.concept_catalog.http.register_routes
  rel: defines
- concept: func:parrot.knowledge.ontology.concept_catalog.http.reject_concept
  rel: defines
- concept: func:parrot.knowledge.ontology.concept_catalog.http.restore_concept
  rel: defines
- concept: func:parrot.knowledge.ontology.concept_catalog.http.submit_concept
  rel: defines
- concept: mod:parrot.knowledge.ontology.concept_catalog.service
  rel: references
- concept: mod:parrot.knowledge.ontology.exceptions
  rel: references
---

# `parrot.knowledge.ontology.concept_catalog.http`

Concept Catalog HTTP Routes (FEAT-159 TASK-1092).

Provides REST API endpoints under ``/api/ontology/concepts/*`` for concept
catalog operations.

Role enforcement (requires ``navigator-auth``):
- ``topic_curator`` (or higher): read and propose operations.
- ``topic_reviewer`` (or higher): approve and reject.
- ``topic_admin``: deprecate and restore.

All responses use JSON serialisation of Pydantic models.
Error mapping:
- ``SynonymConflictError`` → 409 Conflict
- ``CycleError``           → 422 Unprocessable Entity
- ``InvalidTransitionError`` → 422 Unprocessable Entity
- ``KeyError``              → 404 Not Found
- Other exceptions          → 500 Internal Server Error

## Functions

- `async def list_concepts(request: web.Request) -> web.Response` — GET /api/ontology/concepts — list concepts for a tenant.
- `async def get_concept(request: web.Request) -> web.Response` — GET /api/ontology/concepts/{id}
- `async def get_concept_history(request: web.Request) -> web.Response` — GET /api/ontology/concepts/{id}/history
- `async def get_concept_isa(request: web.Request) -> web.Response` — GET /api/ontology/concepts/{id}/isa — is_a subgraph.
- `async def propose_concept(request: web.Request) -> web.Response` — POST /api/ontology/concepts — propose a new concept.
- `async def submit_concept(request: web.Request) -> web.Response` — POST /api/ontology/concepts/{id}/transitions/submit
- `async def approve_concept(request: web.Request) -> web.Response` — POST /api/ontology/concepts/{id}/transitions/approve — reviewer+ only.
- `async def reject_concept(request: web.Request) -> web.Response` — POST /api/ontology/concepts/{id}/transitions/reject — reviewer+ only.
- `async def deprecate_concept(request: web.Request) -> web.Response` — POST /api/ontology/concepts/{id}/transitions/deprecate — admin only.
- `async def restore_concept(request: web.Request) -> web.Response` — POST /api/ontology/concepts/{id}/transitions/restore — admin only.
- `async def modify_concept(request: web.Request) -> web.Response` — PATCH /api/ontology/concepts/{id} — reviewer+ only.
- `async def propose_isa_edge(request: web.Request) -> web.Response` — POST /api/ontology/concepts/isa — propose is_a edge.
- `async def isa_edge_transition(request: web.Request) -> web.Response` — POST /api/ontology/concepts/isa/{id}/transitions/{action}
- `def register_routes(app: web.Application, prefix: str='/api/ontology') -> None` — Register all concept catalog routes on *app*.
