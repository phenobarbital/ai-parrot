"""Read-only HTTP routes of the ontology vocabulary store (FEAT-824)."""
from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from parrot.knowledge.ontology.vocabulary.exceptions import OntologyNotFound, OntologyVersionNotFound
from parrot.knowledge.ontology.vocabulary.settings import resolve_ontology_settings
from parrot.knowledge.ontology.vocabulary.snapshot import build_snapshot

logger = logging.getLogger("parrot.knowledge.ontology.vocabulary.http")
_ADMIN_GROUP = "topic_admin"


def _authorize(request: web.Request, ontology_id: str) -> None:
    """401 without a session; 403 for another tenant's 'tenant.<id>' ontology unless topic_admin."""
    session: dict[str, Any] = request.get("session", {}) or {}
    if not session:
        raise web.HTTPUnauthorized(reason="Authentication required.")

    # Tenant rule: ontology_id starting with 'tenant.' requires matching session tenant or admin
    if ontology_id.startswith("tenant."):
        tenant_part = ontology_id[7:]  # Strip 'tenant.' prefix
        session_tenant = session.get("tenant_id")
        user_groups = set(session.get("groups", []) or [])

        # Allow if session tenant matches, or user is topic_admin
        if session_tenant != tenant_part and _ADMIN_GROUP not in user_groups:
            raise web.HTTPForbidden(reason="Access denied to this tenant's ontology.")


async def get_version(request: web.Request) -> web.Response:
    """GET {prefix}/vocabularies/{ontology_id}/version → {"ontology_id", "version", "checksum"}."""
    ontology_id = request.match_info["ontology_id"]
    _authorize(request, ontology_id)

    store = request.app.get("ontology_store")
    if store is None:
        raise web.HTTPInternalServerError(reason="Ontology store not configured.")

    try:
        # Get current version info
        version = await store.version(ontology_id)
        if version == 0:
            # Registered but never published - return version 0 with no checksum
            return web.json_response({
                "ontology_id": ontology_id,
                "version": 0,
                "checksum": None,
            })

        # Load the version content to get checksum
        content = await store.load_version(ontology_id, version)
        return web.json_response({
            "ontology_id": ontology_id,
            "version": content.version,
            "checksum": content.checksum,
        })
    except OntologyNotFound as exc:
        raise web.HTTPNotFound(reason=str(exc)) from exc
    except OntologyVersionNotFound as exc:
        raise web.HTTPNotFound(reason=str(exc)) from exc


async def get_snapshot(request: web.Request) -> web.StreamResponse:
    """GET {prefix}/vocabularies/{ontology_id}/snapshot[?version=N] → the SQLite file, built on demand and cached."""
    ontology_id = request.match_info["ontology_id"]
    _authorize(request, ontology_id)

    store = request.app.get("ontology_store")
    if store is None:
        raise web.HTTPInternalServerError(reason="Ontology store not configured.")

    # Parse optional version query parameter
    version_param = request.rel_url.query.get("version")
    version: int | None = None
    if version_param is not None:
        try:
            version = int(version_param)
        except ValueError:
            raise web.HTTPBadRequest(reason=f"Invalid version parameter: {version_param!r}") from None

    try:
        # Load the version content
        content = await store.load_version(ontology_id, version)

        # Get snapshot directory from settings
        settings = resolve_ontology_settings()
        snapshot_dir = settings.snapshot_dir

        # Build snapshot (reuses existing if checksum matches)
        path = await build_snapshot(content, snapshot_dir)

        # Stream the file
        return web.FileResponse(path, headers={
            "Content-Type": "application/vnd.sqlite3",
            "Content-Disposition": f'attachment; filename="{ontology_id}-v{content.version}.sqlite"',
        })
    except OntologyNotFound as exc:
        raise web.HTTPNotFound(reason=str(exc)) from exc
    except OntologyVersionNotFound as exc:
        raise web.HTTPNotFound(reason=str(exc)) from exc


async def get_export(request: web.Request) -> web.Response:
    """GET {prefix}/vocabularies/{ontology_id}/export[?as_of=N&fmt=turtle|jsonld]."""
    ontology_id = request.match_info["ontology_id"]
    _authorize(request, ontology_id)

    store = request.app.get("ontology_store")
    if store is None:
        raise web.HTTPInternalServerError(reason="Ontology store not configured.")

    # Parse format query parameter
    fmt = request.rel_url.query.get("fmt", "turtle")
    if fmt not in ("turtle", "jsonld"):
        raise web.HTTPBadRequest(reason=f"Invalid format: {fmt!r}. Supported: turtle, jsonld.")

    # Parse optional as_of query parameter
    as_of_param = request.rel_url.query.get("as_of")
    as_of: int | None = None
    if as_of_param is not None:
        try:
            as_of = int(as_of_param)
        except ValueError:
            raise web.HTTPBadRequest(reason=f"Invalid as_of parameter: {as_of_param!r}") from None

    try:
        # Export the ontology
        data = await store.export(ontology_id, fmt, as_of=as_of)

        content_type = "text/turtle" if fmt == "turtle" else "application/ld+json"
        return web.Response(
            body=data,
            content_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{ontology_id}.{fmt}"',
            },
        )
    except OntologyNotFound as exc:
        raise web.HTTPNotFound(reason=str(exc)) from exc
    except OntologyVersionNotFound as exc:
        raise web.HTTPNotFound(reason=str(exc)) from exc


def register_routes(app: web.Application, prefix: str = "/api/ontology") -> None:
    """Register the three routes; handlers read request.app['ontology_store']."""
    base = f"{prefix}/vocabularies/{{ontology_id}}"
    app.router.add_get(f"{base}/version", get_version)
    app.router.add_get(f"{base}/snapshot", get_snapshot)
    app.router.add_get(f"{base}/export", get_export)
    logger.info("Registered 3 vocabulary routes under '%s'.", base)
