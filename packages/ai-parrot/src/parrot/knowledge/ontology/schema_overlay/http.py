"""Schema Overlay HTTP Routes (FEAT-159 TASK-1097).

Provides REST API endpoints under ``/api/ontology/schema/*`` for schema overlay
operations.  All routes require the ``ontology_schema_admin`` role.

Error mapping:
- ``DryRunFailedError`` → 422 with ``dry_run_report`` in body.
- ``InvalidTransitionError`` → 422 Unprocessable Entity.
- ``KeyError`` → 404 Not Found.
- Other exceptions → 500 Internal Server Error.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from aiohttp import web

from parrot.knowledge.ontology.exceptions import (
    DryRunFailedError,
    InvalidTransitionError,
)
from parrot.knowledge.ontology.schema_overlay.service import SchemaOverlayService

logger = logging.getLogger("Parrot.Ontology.SchemaOverlay.HTTP")

_SCHEMA_ADMIN = "ontology_schema_admin"
_TOPIC_ADMIN = "topic_admin"


def _check_role(request: web.Request, allowed_roles: set[str]) -> str:
    """Verify role and return tenant_id.

    Raises:
        web.HTTPUnauthorized: If no session.
        web.HTTPForbidden: If user lacks the required role.
    """
    session: dict[str, Any] = request.get("session", {}) or {}
    if not session:
        raise web.HTTPUnauthorized(reason="Authentication required.")

    user_roles: set[str] = set(session.get("groups", []) or [])
    if not user_roles.intersection(allowed_roles):
        raise web.HTTPForbidden(
            reason=f"Role required: one of {sorted(allowed_roles)}."
        )

    return (
        session.get("tenant_id")
        or request.rel_url.query.get("tenant")
        or ""
    )


def _parse_uuid(value: str, name: str = "id") -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise web.HTTPBadRequest(reason=f"Invalid UUID for '{name}': {value!r}")


def _error_response(exc: Exception) -> web.Response:
    if isinstance(exc, DryRunFailedError):
        return web.json_response(
            {
                "error": "DryRunFailed",
                "detail": str(exc),
                "dry_run_report": exc.report,
            },
            status=422,
        )
    if isinstance(exc, InvalidTransitionError):
        return web.json_response(
            {"error": "InvalidTransition", "detail": str(exc)},
            status=422,
        )
    if isinstance(exc, KeyError):
        return web.json_response({"error": "NotFound", "detail": str(exc)}, status=404)
    logger.exception("Unexpected error in schema overlay route: %s", exc)
    return web.json_response(
        {"error": "InternalServerError", "detail": str(exc)},
        status=500,
    )


# ── Route handlers ────────────────────────────────────────────────────────────

async def list_overlays(request: web.Request) -> web.Response:
    """GET /api/ontology/schema — list pending overlays for tenant."""
    try:
        tenant_id = _check_role(request, {_SCHEMA_ADMIN})
        svc: SchemaOverlayService = request.app["schema_overlay_service"]
        pending = await svc.get_pending(tenant_id)
        return web.json_response(
            {"items": [o.model_dump(mode="json") for o in pending]}
        )
    except web.HTTPException:
        raise
    except Exception as exc:
        return _error_response(exc)


async def get_overlay(request: web.Request) -> web.Response:
    """GET /api/ontology/schema/{id}"""
    try:
        tenant_id = _check_role(request, {_SCHEMA_ADMIN})
        overlay_id = _parse_uuid(request.match_info["id"])
        svc: SchemaOverlayService = request.app["schema_overlay_service"]
        pending = await svc.get_pending(tenant_id)
        match = next((o for o in pending if o.id == overlay_id), None)
        if match is None:
            return web.json_response({"error": "NotFound"}, status=404)
        return web.json_response(match.model_dump(mode="json"))
    except web.HTTPException:
        raise
    except Exception as exc:
        return _error_response(exc)


async def dry_run_overlay_endpoint(request: web.Request) -> web.Response:
    """GET /api/ontology/schema/{id}/dry-run — run validation without approving."""
    try:
        tenant_id = _check_role(request, {_SCHEMA_ADMIN})
        overlay_id = _parse_uuid(request.match_info["id"])
        svc: SchemaOverlayService = request.app["schema_overlay_service"]

        # Fetch the overlay row
        pending = await svc.get_pending(tenant_id)
        overlay = next((o for o in pending if o.id == overlay_id), None)
        if overlay is None:
            return web.json_response({"error": "NotFound"}, status=404)

        # Run dry-run via validator directly
        from parrot.knowledge.ontology.schema_overlay.validator import dry_run_overlay
        tenant_manager = request.app.get("tenant_manager")
        merger = request.app.get("ontology_merger")
        report = await dry_run_overlay(tenant_id, overlay, tenant_manager, merger)
        return web.json_response(report.model_dump(mode="json"))
    except web.HTTPException:
        raise
    except Exception as exc:
        return _error_response(exc)


async def propose_overlay(request: web.Request) -> web.Response:
    """POST /api/ontology/schema — propose a new schema overlay."""
    try:
        tenant_id = _check_role(request, {_SCHEMA_ADMIN})
        body = await request.json()
        session = request.get("session", {}) or {}
        actor = session.get("email", "unknown")
        svc: SchemaOverlayService = request.app["schema_overlay_service"]
        overlay_id = await svc.propose(
            tenant_id=tenant_id,
            overlay_kind=body["overlay_kind"],
            name=body["name"],
            definition=body["definition"],
            asserted_by=actor,
            rationale=body.get("rationale"),
        )
        return web.json_response({"id": str(overlay_id)}, status=201)
    except web.HTTPException:
        raise
    except Exception as exc:
        return _error_response(exc)


async def overlay_transition(request: web.Request) -> web.Response:
    """POST /api/ontology/schema/{id}/transitions/{action}"""
    try:
        _check_role(request, {_SCHEMA_ADMIN})
        overlay_id = _parse_uuid(request.match_info["id"])
        action = request.match_info["action"]
        session = request.get("session", {}) or {}
        actor = session.get("email", "unknown")
        svc: SchemaOverlayService = request.app["schema_overlay_service"]

        body: dict = {}
        try:
            body = await request.json()
        except Exception:
            pass

        if action == "submit":
            await svc.submit(overlay_id, actor)
        elif action == "approve":
            await svc.approve(overlay_id, actor, reason=body.get("reason"))
        elif action == "reject":
            await svc.reject(overlay_id, actor, reason=body.get("reason"))
        elif action == "deprecate":
            await svc.deprecate(overlay_id, actor, reason=body.get("reason"))
        elif action == "restore":
            await svc.restore(overlay_id, actor)
        else:
            return web.json_response({"error": f"Unknown action: {action!r}"}, status=400)

        return web.json_response({"status": action})
    except web.HTTPException:
        raise
    except Exception as exc:
        return _error_response(exc)


# ── Route registration ────────────────────────────────────────────────────────

def register_routes(app: web.Application, prefix: str = "/api/ontology") -> None:
    """Register all schema overlay routes on *app*.

    Args:
        app: aiohttp Application instance.
        prefix: URL prefix (default ``/api/ontology``).
    """
    base = f"{prefix}/schema"
    app.router.add_get(base, list_overlays)
    app.router.add_get(f"{base}/{{id}}", get_overlay)
    app.router.add_get(f"{base}/{{id}}/dry-run", dry_run_overlay_endpoint)
    app.router.add_post(base, propose_overlay)
    app.router.add_post(f"{base}/{{id}}/transitions/{{action}}", overlay_transition)

    logger.info("Registered 5 schema overlay routes under '%s'.", base)
