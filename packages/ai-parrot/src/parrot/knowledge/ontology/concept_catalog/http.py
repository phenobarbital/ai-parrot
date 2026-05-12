"""Concept Catalog HTTP Routes (FEAT-159 TASK-1092).

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
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from aiohttp import web

from parrot.knowledge.ontology.concept_catalog.service import ConceptCatalogService
from parrot.knowledge.ontology.exceptions import (
    CycleError,
    InvalidTransitionError,
    SynonymConflictError,
)

logger = logging.getLogger("Parrot.Ontology.ConceptCatalog.HTTP")

# Role constants
_CURATOR = "topic_curator"
_REVIEWER = "topic_reviewer"
_ADMIN = "topic_admin"

# All roles that can perform curator-level actions
_CURATOR_PLUS = {_CURATOR, _REVIEWER, _ADMIN}
_REVIEWER_PLUS = {_REVIEWER, _ADMIN}
_ADMIN_ONLY = {_ADMIN}


def _check_role(request: web.Request, allowed_roles: set[str]) -> str | None:
    """Extract tenant_id from session and verify role.

    Returns:
        tenant_id if authorised, otherwise raises ``web.HTTPForbidden``.

    Raises:
        web.HTTPForbidden: If the user lacks the required role.
        web.HTTPUnauthorized: If no session exists.
    """
    session: dict[str, Any] = request.get("session", {}) or {}
    user_roles: set[str] = set(session.get("groups", []) or [])
    tenant_id: str | None = session.get("tenant_id") or request.rel_url.query.get("tenant")

    if not session:
        raise web.HTTPUnauthorized(reason="Authentication required.")

    if not user_roles.intersection(allowed_roles):
        raise web.HTTPForbidden(
            reason=f"Role required: one of {sorted(allowed_roles)}."
        )

    return tenant_id or ""


def _parse_uuid(value: str, name: str = "id") -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise web.HTTPBadRequest(reason=f"Invalid UUID for '{name}': {value!r}")


def _error_response(exc: Exception) -> web.Response:
    if isinstance(exc, SynonymConflictError):
        return web.json_response(
            {"error": "SynonymConflict", "detail": str(exc), "synonym": exc.synonym},
            status=409,
        )
    if isinstance(exc, (CycleError, InvalidTransitionError)):
        return web.json_response(
            {"error": type(exc).__name__, "detail": str(exc)},
            status=422,
        )
    if isinstance(exc, KeyError):
        return web.json_response(
            {"error": "NotFound", "detail": str(exc)},
            status=404,
        )
    logger.exception("Unexpected error in concept catalog route: %s", exc)
    return web.json_response(
        {"error": "InternalServerError", "detail": str(exc)},
        status=500,
    )


# ── Route functions ───────────────────────────────────────────────────────────

async def list_concepts(request: web.Request) -> web.Response:
    """GET /api/ontology/concepts — list concepts for a tenant.

    Query params: ``tenant`` (required if not in session), ``state``, ``domain``,
    ``limit`` (default 50, max 200), ``offset`` (default 0).
    """
    try:
        tenant_id = _check_role(request, _CURATOR_PLUS)
        svc: ConceptCatalogService = request.app["concept_catalog_service"]
        domain = request.rel_url.query.get("domain")
        concepts = await svc.get_live_concepts(tenant_id, domain=domain)
        data = [c.model_dump(mode="json") for c in concepts]
        # Pagination
        limit = min(int(request.rel_url.query.get("limit", 50)), 200)
        offset = int(request.rel_url.query.get("offset", 0))
        page = data[offset: offset + limit]
        return web.json_response({"items": page, "total": len(data)})
    except (web.HTTPException, web.HTTPForbidden, web.HTTPUnauthorized) as exc:
        raise
    except Exception as exc:
        return _error_response(exc)


async def get_concept(request: web.Request) -> web.Response:
    """GET /api/ontology/concepts/{id}"""
    try:
        tenant_id = _check_role(request, _CURATOR_PLUS)
        concept_id = _parse_uuid(request.match_info["id"])
        svc: ConceptCatalogService = request.app["concept_catalog_service"]
        concepts = await svc.get_live_concepts(tenant_id)
        match = next((c for c in concepts if c.id == concept_id), None)
        if match is None:
            return web.json_response({"error": "NotFound"}, status=404)
        return web.json_response(match.model_dump(mode="json"))
    except (web.HTTPException,) as exc:
        raise
    except Exception as exc:
        return _error_response(exc)


async def get_concept_history(request: web.Request) -> web.Response:
    """GET /api/ontology/concepts/{id}/history"""
    try:
        _check_role(request, _CURATOR_PLUS)
        concept_id = _parse_uuid(request.match_info["id"])
        svc: ConceptCatalogService = request.app["concept_catalog_service"]
        history = await svc.get_history(concept_id)
        return web.json_response({"items": history})
    except (web.HTTPException,) as exc:
        raise
    except Exception as exc:
        return _error_response(exc)


async def get_concept_isa(request: web.Request) -> web.Response:
    """GET /api/ontology/concepts/{id}/isa — is_a subgraph."""
    try:
        _check_role(request, _CURATOR_PLUS)
        concept_id = _parse_uuid(request.match_info["id"])
        svc: ConceptCatalogService = request.app["concept_catalog_service"]
        subgraph = await svc.get_isa_subgraph(concept_id)
        return web.json_response({"items": subgraph})
    except (web.HTTPException,) as exc:
        raise
    except Exception as exc:
        return _error_response(exc)


async def propose_concept(request: web.Request) -> web.Response:
    """POST /api/ontology/concepts — propose a new concept."""
    try:
        tenant_id = _check_role(request, _CURATOR_PLUS)
        body = await request.json()
        svc: ConceptCatalogService = request.app["concept_catalog_service"]
        session = request.get("session", {}) or {}
        actor = session.get("email", "unknown")
        concept_id = await svc.propose_concept(
            tenant_id=tenant_id,
            slug=body["slug"],
            label=body["label"],
            asserted_by=actor,
            description=body.get("description"),
            synonyms=body.get("synonyms", []),
            domain=body.get("domain"),
        )
        return web.json_response({"id": str(concept_id)}, status=201)
    except (web.HTTPException,) as exc:
        raise
    except Exception as exc:
        return _error_response(exc)


async def submit_concept(request: web.Request) -> web.Response:
    """POST /api/ontology/concepts/{id}/transitions/submit"""
    try:
        _check_role(request, _CURATOR_PLUS)
        concept_id = _parse_uuid(request.match_info["id"])
        svc: ConceptCatalogService = request.app["concept_catalog_service"]
        session = request.get("session", {}) or {}
        actor = session.get("email", "unknown")
        await svc.submit_for_review(concept_id, "concept", actor)
        return web.json_response({"status": "submitted"})
    except (web.HTTPException,) as exc:
        raise
    except Exception as exc:
        return _error_response(exc)


async def approve_concept(request: web.Request) -> web.Response:
    """POST /api/ontology/concepts/{id}/transitions/approve — reviewer+ only."""
    try:
        _check_role(request, _REVIEWER_PLUS)
        concept_id = _parse_uuid(request.match_info["id"])
        svc: ConceptCatalogService = request.app["concept_catalog_service"]
        session = request.get("session", {}) or {}
        actor = session.get("email", "unknown")
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        await svc.approve(concept_id, "concept", actor, reason=body.get("reason"))
        return web.json_response({"status": "approved"})
    except (web.HTTPException,) as exc:
        raise
    except Exception as exc:
        return _error_response(exc)


async def reject_concept(request: web.Request) -> web.Response:
    """POST /api/ontology/concepts/{id}/transitions/reject — reviewer+ only."""
    try:
        _check_role(request, _REVIEWER_PLUS)
        concept_id = _parse_uuid(request.match_info["id"])
        svc: ConceptCatalogService = request.app["concept_catalog_service"]
        session = request.get("session", {}) or {}
        actor = session.get("email", "unknown")
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        await svc.reject(concept_id, "concept", actor)
        return web.json_response({"status": "rejected"})
    except (web.HTTPException,) as exc:
        raise
    except Exception as exc:
        return _error_response(exc)


async def deprecate_concept(request: web.Request) -> web.Response:
    """POST /api/ontology/concepts/{id}/transitions/deprecate — admin only."""
    try:
        _check_role(request, _ADMIN_ONLY)
        concept_id = _parse_uuid(request.match_info["id"])
        svc: ConceptCatalogService = request.app["concept_catalog_service"]
        session = request.get("session", {}) or {}
        actor = session.get("email", "unknown")
        await svc.deprecate(concept_id, "concept", actor)
        return web.json_response({"status": "deprecated"})
    except (web.HTTPException,) as exc:
        raise
    except Exception as exc:
        return _error_response(exc)


async def restore_concept(request: web.Request) -> web.Response:
    """POST /api/ontology/concepts/{id}/transitions/restore — admin only."""
    try:
        _check_role(request, _ADMIN_ONLY)
        concept_id = _parse_uuid(request.match_info["id"])
        svc: ConceptCatalogService = request.app["concept_catalog_service"]
        session = request.get("session", {}) or {}
        actor = session.get("email", "unknown")
        await svc.restore(concept_id, "concept", actor)
        return web.json_response({"status": "restored"})
    except (web.HTTPException,) as exc:
        raise
    except Exception as exc:
        return _error_response(exc)


async def modify_concept(request: web.Request) -> web.Response:
    """PATCH /api/ontology/concepts/{id} — reviewer+ only."""
    try:
        _check_role(request, _REVIEWER_PLUS)
        concept_id = _parse_uuid(request.match_info["id"])
        svc: ConceptCatalogService = request.app["concept_catalog_service"]
        session = request.get("session", {}) or {}
        actor = session.get("email", "unknown")
        body = await request.json()
        await svc.modify_metadata(
            concept_id, "concept", actor,
            label=body.get("label"),
            description=body.get("description"),
            synonyms=body.get("synonyms"),
            domain=body.get("domain"),
        )
        return web.json_response({"status": "updated"})
    except (web.HTTPException,) as exc:
        raise
    except Exception as exc:
        return _error_response(exc)


async def propose_isa_edge(request: web.Request) -> web.Response:
    """POST /api/ontology/concepts/isa — propose is_a edge."""
    try:
        tenant_id = _check_role(request, _CURATOR_PLUS)
        body = await request.json()
        svc: ConceptCatalogService = request.app["concept_catalog_service"]
        session = request.get("session", {}) or {}
        actor = session.get("email", "unknown")
        edge_id = await svc.propose_isa_edge(
            tenant_id=tenant_id,
            child_id=UUID(body["child_id"]),
            parent_tier=body["parent_tier"],
            parent_ref=body["parent_ref"],
            asserted_by=actor,
        )
        return web.json_response({"id": str(edge_id)}, status=201)
    except (web.HTTPException,) as exc:
        raise
    except Exception as exc:
        return _error_response(exc)


async def isa_edge_transition(request: web.Request) -> web.Response:
    """POST /api/ontology/concepts/isa/{id}/transitions/{action}"""
    try:
        action = request.match_info["action"]
        edge_id = _parse_uuid(request.match_info["id"])
        svc: ConceptCatalogService = request.app["concept_catalog_service"]
        session = request.get("session", {}) or {}
        actor = session.get("email", "unknown")

        # Role enforcement per action
        if action in ("approve",):
            _check_role(request, _REVIEWER_PLUS)
        elif action in ("deprecate", "restore"):
            _check_role(request, _ADMIN_ONLY)
        else:
            _check_role(request, _CURATOR_PLUS)

        if action == "approve":
            await svc.approve(edge_id, "isa_edge", actor)
        elif action == "reject":
            await svc.reject(edge_id, "isa_edge", actor)
        elif action == "deprecate":
            await svc.deprecate(edge_id, "isa_edge", actor)
        elif action == "restore":
            await svc.restore(edge_id, "isa_edge", actor)
        elif action == "submit":
            await svc.submit_for_review(edge_id, "isa_edge", actor)
        else:
            return web.json_response({"error": f"Unknown action: {action!r}"}, status=400)

        return web.json_response({"status": action})
    except (web.HTTPException,) as exc:
        raise
    except Exception as exc:
        return _error_response(exc)


# ── Route registration ────────────────────────────────────────────────────────

def register_routes(app: web.Application, prefix: str = "/api/ontology") -> None:
    """Register all concept catalog routes on *app*.

    Args:
        app: aiohttp Application instance.
        prefix: URL prefix for the routes (default ``/api/ontology``).
    """
    base = f"{prefix}/concepts"
    app.router.add_get(base, list_concepts)
    app.router.add_get(f"{base}/{{id}}", get_concept)
    app.router.add_get(f"{base}/{{id}}/history", get_concept_history)
    app.router.add_get(f"{base}/{{id}}/isa", get_concept_isa)
    app.router.add_post(base, propose_concept)
    app.router.add_post(f"{base}/{{id}}/transitions/submit", submit_concept)
    app.router.add_post(f"{base}/{{id}}/transitions/approve", approve_concept)
    app.router.add_post(f"{base}/{{id}}/transitions/reject", reject_concept)
    app.router.add_post(f"{base}/{{id}}/transitions/deprecate", deprecate_concept)
    app.router.add_post(f"{base}/{{id}}/transitions/restore", restore_concept)
    app.router.add_patch(f"{base}/{{id}}", modify_concept)
    app.router.add_post(f"{base}/isa", propose_isa_edge)
    app.router.add_post(f"{base}/isa/{{id}}/transitions/{{action}}", isa_edge_transition)

    logger.info("Registered %d concept catalog routes under '%s'.", 13, base)
