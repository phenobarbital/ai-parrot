"""SurfaceNegotiationService + UISurfacesHandler — REST lane for the
ui_surfaces plane (FEAT-492, Module 3).

``SurfaceNegotiationService`` is the SHARED JSON/HTML negotiation service:
both this handler's ``GET`` and ``A2UIHandler``'s mirror route (TASK-2703)
delegate to the same instance/logic so negotiation behavior cannot drift.

``UISurfacesHandler`` (``navigator.views.BaseView`` + ``@is_authenticated()``/
``@user_session()``, the ``AgentTalk``/``DashboardHandler`` idiom) dispatches
on ``match_info``/path suffix inside ``get``/``post``/``delete`` — one
handler class for the whole REST lane (``InfographicTalk`` precedent).

Route registration itself is TASK-2703's job — this module only defines the
service + handler classes.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from aiohttp import web
from navigator.views import BaseView
from navigator_auth.conf import AUTH_SESSION_OBJECT
from navigator_auth.decorators import is_authenticated, user_session
from navigator_session import get_session
from parrot.auth.permission import build_principal_context
from parrot.handlers.infographic_recipes import get_recipe_runner
from parrot.handlers.models.ui_surfaces import (
    PgUISurfaceStore,
    UISurfaceKind,
    UISurfaceRecord,
)
from parrot.outputs.a2ui.models import CreateSurface
from parrot.storage.artifacts import ArtifactStore
from parrot.tools.infographic_recipes.runner import RecipeRunException, RecipeRunner
from pydantic import BaseModel, Field, ValidationError

__all__ = [
    "MintShareRequest",
    "PublishSurfaceRequest",
    "RefreshSurfaceRequest",
    "SurfaceNegotiationService",
    "UISurfacesHandler",
    "resolve_surface_access",
]

logger = logging.getLogger("Parrot.UISurfaces")


# ---------------------------------------------------------------------------
# Wire models (spec §2 Data Models)
# ---------------------------------------------------------------------------


class PublishSurfaceRequest(BaseModel):
    """Body of ``POST /api/v1/ui/surfaces`` (frontend pin/save).

    Note: adds ``session_id`` beyond the spec's Data Models block — copying
    from ``ArtifactStore`` needs the full ``(user_id, agent_id, session_id,
    artifact_id)`` composite key (``storage/artifacts.py``); ``user_id``
    comes from the authenticated session, but ``session_id`` has no other
    source. Optional and additive — inline-envelope publishes never need it.
    """

    kind: UISurfaceKind
    title: str
    envelope: dict[str, Any] | None = None
    source_artifact_id: str | None = None
    agent_id: str | None = None
    session_id: str | None = None
    recipe_name: str | None = None
    recipe_owner: str | None = None
    recipe_params: dict[str, Any] = Field(default_factory=dict)


class RefreshSurfaceRequest(BaseModel):
    """Body of ``POST /api/v1/ui/surfaces/{id}/refresh``."""

    params: dict[str, Any] = Field(default_factory=dict)


class MintShareRequest(BaseModel):
    """Body of ``POST /api/v1/ui/surfaces/{id}/share``."""

    expires_at: datetime | None = None
    ttl: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_user_id(request: web.Request) -> str | None:
    """Extract the authenticated user's id from the request/session.

    Mirrors ``handlers/infographic_recipes.py``/``handlers/artifacts.py``'s
    identically-named private helper.
    """
    user = getattr(request, "user", None)
    if user:
        uid = getattr(user, "user_id", None) or getattr(user, "id", None)
        if uid:
            return str(uid)
    try:
        session = await get_session(request)
    except Exception:  # noqa: BLE001
        return None
    if session:
        userinfo = session.get(AUTH_SESSION_OBJECT, {})
        if isinstance(userinfo, dict):
            user_id = userinfo.get("user_id")
            if user_id:
                return str(user_id)
        user_id = session.get("user_id")
        if user_id:
            return str(user_id)
    return None


def _surface_metadata(record: UISurfaceRecord) -> dict[str, Any]:
    """Common JSON metadata block shared by the negotiated GET and list endpoint."""
    return {
        "surface_id": record.surface_id,
        "kind": record.kind.value,
        "title": record.title,
        "refreshable": record.refreshable,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "catalog_id": record.catalog_id,
        "agent_id": record.agent_id,
    }


async def resolve_surface_access(
    store: PgUISurfaceStore, surface_id: str, user_id: str | None, token: str | None
) -> tuple[UISurfaceRecord | None, tuple[str, int] | None]:
    """Resolve owner-or-share access to a surface.

    SHARED between ``UISurfacesHandler`` (this module) and
    ``A2UIHandler``'s mirror route (``handlers/a2ui.py``, TASK-2703) — code
    review follow-up: this rule set was originally duplicated between the
    two handlers (each building its own ``web.Response``); promoted to a
    module-level, framework-response-agnostic function so it cannot drift
    between the two routes. Returns ``(record, None)`` on success, or
    ``(None, (message, status))`` on failure — the caller builds the actual
    ``web.Response`` with its own response helper.

    Unknown/foreign-without-token id -> 404 (no existence oracle).
    Revoked/expired/missing token (when one WAS supplied) -> 410.
    """
    record = await store.get(surface_id)
    if record is None:
        return None, ("Surface not found", 404)
    if record.user_id == user_id:
        return record, None
    if token:
        share = await store.resolve_share(token)
        if share is None or share.surface_id != surface_id:
            return None, ("Share link invalid or expired", 410)
        if user_id:
            await store.claim_share(token, user_id)
        return record, None
    return None, ("Surface not found", 404)


# ---------------------------------------------------------------------------
# SurfaceNegotiationService
# ---------------------------------------------------------------------------


class SurfaceNegotiationService:
    """Shared JSON/HTML negotiation over a stored surface (used by BOTH handlers).

    ``UISurfacesHandler.get()`` and ``A2UIHandler``'s mirror route
    (TASK-2703) both delegate to the SAME logic here so negotiation behavior
    cannot drift between the two routes (spec §2 resolved decision).
    """

    def negotiate(self, request: web.Request) -> str:
        """Resolve the desired content type for the response.

        Priority: ``?format=`` query param (wins) > ``Accept`` header >
        default ``application/json`` (unlike ``InfographicTalk``, whose
        default is HTML — this lane defaults to JSON, spec §2).

        Args:
            request: The incoming aiohttp request.

        Returns:
            ``"application/json"`` or ``"text/html"``.
        """
        fmt = (request.query.get("format") or "").lower()
        if fmt == "html":
            return "text/html"
        if fmt == "json":
            return "application/json"
        accept_header = request.headers.get("Accept", "")
        if "text/html" in accept_header:
            return "text/html"
        return "application/json"

    async def respond(self, record: UISurfaceRecord, accept: str) -> web.Response:
        """Build the negotiated response for a resolved surface record.

        Args:
            record: The persisted surface to serve.
            accept: ``"application/json"`` or ``"text/html"`` (from
                :meth:`negotiate`).

        Returns:
            A JSON envelope+metadata response, or an on-the-fly rendered
            interactive HTML response (501 with an install hint when
            ai-parrot-visualizations is not installed).
        """
        if accept == "text/html":
            return await self._respond_html(record)
        return self._respond_json(record)

    def _respond_json(self, record: UISurfaceRecord) -> web.Response:
        return web.json_response(
            {
                "status": "success",
                "envelope": record.envelope,
                "metadata": _surface_metadata(record),
            }
        )

    async def _respond_html(self, record: UISurfaceRecord) -> web.Response:
        try:
            from parrot.outputs.a2ui_renderers.interactive_html import (
                InteractiveHTMLRenderer,
            )
        except ImportError:
            return web.json_response(
                {
                    "status": "error",
                    "message": (
                        "HTML rendering requires ai-parrot-visualizations. "
                        "Install with: pip install ai-parrot-visualizations"
                    ),
                },
                status=501,
            )
        try:
            envelope = CreateSurface.model_validate(record.envelope)
            renderer = InteractiveHTMLRenderer()
            artifact = await renderer.render(envelope)
        except Exception as exc:  # any render failure is a client-visible 422
            logger.exception("UISurfaces HTML render failed for surface %s", record.surface_id)
            return web.json_response(
                {
                    "status": "error",
                    "message": f"Stored surface could not be rendered: {exc}",
                    "surface_id": record.surface_id,
                },
                status=422,
            )
        return web.Response(body=artifact.content, content_type="text/html")


# ---------------------------------------------------------------------------
# UISurfacesHandler
# ---------------------------------------------------------------------------


@is_authenticated()
@user_session()
class UISurfacesHandler(BaseView):
    """REST lane for the ui_surfaces plane (spec §3 Module 3).

    Dispatches on ``match_info``/path suffix inside ``get``/``post``/
    ``delete`` — one handler class, ``InfographicTalk``/``RecipeHandler``
    idiom — rather than a route per sub-path.
    """

    _logger_name: str = "Parrot.UISurfaces"

    def post_init(self, *args, **kwargs) -> None:
        self.logger = logging.getLogger(self._logger_name)

    # ── Wiring (app-context, InfographicRecipes precedent) ──────────────

    @property
    def store(self) -> PgUISurfaceStore:
        store = self.request.app.get("ui_surfaces_store")
        if store is None:
            store = PgUISurfaceStore()
            self.request.app["ui_surfaces_store"] = store
        return store

    @property
    def negotiation(self) -> SurfaceNegotiationService:
        service = self.request.app.get("ui_surfaces_negotiation")
        if service is None:
            service = SurfaceNegotiationService()
            self.request.app["ui_surfaces_negotiation"] = service
        return service

    def _recipe_runner(self) -> RecipeRunner | None:
        """Reuse the process-wide RecipeRunner wired by ``register_recipe_routes()``."""
        return self.request.app.get("recipe_runner") or get_recipe_runner()

    def _artifact_store(self) -> ArtifactStore | None:
        return self.request.app.get("artifact_store")

    async def _user_id(self) -> str | None:
        return await _get_user_id(self.request)

    def _error(self, message: str, *, status: int = 400) -> web.Response:
        """Build a JSON error response directly via ``json_response``.

        ``BaseView.error()`` only recognizes a fixed status whitelist
        (400/401/403/404/406/412/428 — ``navigator/views/base.py``) and
        silently falls back to ``HTTPBadRequest`` (400) for anything else
        (the same landmine documented in ``handlers/comm_center.py``'s
        ``_map_error``) — this handler needs 409/410/422/500/501/502/503 too,
        so every error response is built directly instead, matching
        ``RecipeHandler._error_response``'s approach in the sibling
        ``infographic_recipes.py`` handler.
        """
        return self.json_response({"status": "error", "message": message}, status=status)

    # ── Public HTTP verbs ────────────────────────────────────────────────

    async def get(self) -> web.Response:
        """``GET /api/v1/ui/surfaces[/{surface_id}]``."""
        surface_id = self.request.match_info.get("surface_id")
        user_id = await self._user_id()
        if surface_id:
            return await self._get_one(surface_id, user_id)
        return await self._get_list(user_id)

    async def post(self) -> web.Response:
        """Dispatch ``POST`` by path suffix: ``/refresh``, ``/share``, or pin/save."""
        path = self.request.path
        if path.endswith("/refresh"):
            return await self._refresh()
        if path.endswith("/share"):
            return await self._mint_share()
        return await self._pin_save()

    async def delete(self) -> web.Response:
        """Dispatch ``DELETE``: revoke a share token, or delete a surface."""
        surface_id = self.request.match_info.get("surface_id")
        token = self.request.match_info.get("token")
        if token:
            return await self._revoke_share(surface_id, token)
        return await self._delete_surface(surface_id)

    # ── GET ──────────────────────────────────────────────────────────────

    async def _resolve_surface_for_access(
        self, surface_id: str, user_id: str | None, token: str | None
    ) -> tuple[UISurfaceRecord | None, web.Response | None]:
        """Resolve owner-or-share access to a surface.

        Thin wrapper building this handler's OWN ``web.Response`` from the
        SHARED :func:`resolve_surface_access` rule set (module-level —
        also used by ``A2UIHandler``'s mirror route, TASK-2703 — so the
        rule set cannot drift between the two routes).

        Returns:
            ``(record, None)`` on success, or ``(None, error_response)``.
        """
        record, error = await resolve_surface_access(self.store, surface_id, user_id, token)
        if error is None:
            return record, None
        message, status = error
        # self._error() always builds the response directly via
        # json_response — never BaseView.error() and its status whitelist
        # landmine (see _error's own docstring) — so any status works here,
        # including 410 (NOT in that whitelist).
        return None, self._error(message, status=status)

    async def _get_one(self, surface_id: str, user_id: str | None) -> web.Response:
        qs = self.query_parameters(self.request)
        token = qs.get("share")
        record, err = await self._resolve_surface_for_access(surface_id, user_id, token)
        if err is not None:
            return err
        accept = self.negotiation.negotiate(self.request)
        return await self.negotiation.respond(record, accept)

    async def _get_list(self, user_id: str | None) -> web.Response:
        if not user_id:
            return self._error("User ID not found in session", status=401)
        qs = self.query_parameters(self.request)
        kind_str = qs.get("kind")
        kind: UISurfaceKind | None = None
        if kind_str:
            try:
                kind = UISurfaceKind(kind_str)
            except ValueError:
                return self._error(f"Unknown kind: {kind_str!r}", status=400)

        owned = await self.store.list(user_id, kind=kind)
        shared = await self.store.list_shared_with(user_id)
        if kind is not None:
            shared = [r for r in shared if r.kind == kind]

        items = [{**_surface_metadata(r), "access": "owner"} for r in owned] + [
            {**_surface_metadata(r), "access": "shared"} for r in shared
        ]
        return self.json_response({"status": "success", "count": len(items), "surfaces": items})

    # ── POST: pin/save ──────────────────────────────────────────────────

    async def _pin_save(self) -> web.Response:
        user_id = await self._user_id()
        if not user_id:
            return self._error("User ID not found in session", status=401)
        try:
            body = await self.request.json()
        except Exception:  # noqa: BLE001
            return self._error("Invalid JSON body", status=400)
        if not isinstance(body, dict):
            return self._error("Request body must be a JSON object", status=400)

        try:
            req = PublishSurfaceRequest.model_validate(body)
        except ValidationError as exc:
            return self.json_response(
                {"status": "error", "message": "Invalid request", "errors": exc.errors()},
                status=400,
            )

        has_inline = req.envelope is not None
        has_artifact = req.source_artifact_id is not None
        if has_inline == has_artifact:
            return self._error("Exactly one of envelope or source_artifact_id is required", status=400)

        if has_inline:
            envelope_dict = req.envelope
        else:
            artifact_store = self._artifact_store()
            if artifact_store is None:
                # 503 is NOT in BaseView.error()'s status whitelist — build
                # the response directly (same reasoning as the 410 above).
                return self.json_response(
                    {"status": "error", "message": "Artifact store not available"},
                    status=503,
                )
            if not req.agent_id or not req.session_id:
                return self._error(
                    "agent_id and session_id are required to copy from an artifact",
                    status=400,
                )
            artifact = await artifact_store.get_artifact(
                user_id=user_id,
                agent_id=req.agent_id,
                session_id=req.session_id,
                artifact_id=req.source_artifact_id,
            )
            if artifact is None or artifact.definition is None:
                return self._error(f"Artifact {req.source_artifact_id} not found", status=404)
            envelope_dict = artifact.definition

        try:
            envelope = CreateSurface.model_validate(envelope_dict)
        except ValidationError as exc:
            return self.json_response(
                {"status": "error", "message": "Invalid envelope", "errors": exc.errors()},
                status=400,
            )

        now = datetime.now(UTC)
        record = UISurfaceRecord(
            surface_id=str(uuid.uuid4()),
            kind=req.kind,
            title=req.title,
            envelope=envelope.model_dump(by_alias=True, mode="json"),
            catalog_id=envelope.catalog_id,
            agent_id=req.agent_id or "",
            user_id=user_id,
            session_id=req.session_id,
            recipe_name=req.recipe_name,
            recipe_owner=req.recipe_owner,
            recipe_params=req.recipe_params,
            created_at=now,
            updated_at=now,
        )
        surface_id = await self.store.save(record)
        return self.json_response({"status": "success", "surface_id": surface_id}, status=201)

    # ── POST: refresh ────────────────────────────────────────────────────

    async def _refresh(self) -> web.Response:
        surface_id = self.request.match_info.get("surface_id")
        if not surface_id:
            return self._error("surface_id is required", status=400)

        user_id = await self._user_id()
        qs = self.query_parameters(self.request)
        token = qs.get("share")
        record, err = await self._resolve_surface_for_access(surface_id, user_id, token)
        if err is not None:
            return err

        if not record.refreshable:
            return self.json_response(
                {
                    "status": "error",
                    "message": "Surface has no recipe_ref and cannot be refreshed",
                    "refreshable": False,
                },
                status=409,
            )

        try:
            body = await self.request.json()
        except Exception:  # noqa: BLE001
            body = {}
        req = RefreshSurfaceRequest.model_validate(body if isinstance(body, dict) else {})
        # Param precedence: request > stored recipe_params > recipe defaults
        # (recipe defaults are applied inside RecipeRunner._resolve_params_or_raise).
        merged_params = {**record.recipe_params, **req.params}

        runner = self._recipe_runner()
        if runner is None:
            # 500 is NOT in BaseView.error()'s status whitelist — build the
            # response directly (same reasoning as the 410/503 above).
            return self.json_response(
                {"status": "error", "message": "recipe_runner is not configured"},
                status=500,
            )

        # Share-bearer refresh runs with the OWNER's PermissionContext —
        # never the bearer's identity (spec Known Risk).
        owner_pctx = build_principal_context(record.user_id, channel="ui_surfaces")

        try:
            artifact = await runner.run(
                record.recipe_name,
                params=merged_params,
                pctx=owner_pctx,
                recipe_owner=record.recipe_owner,
                include_envelope=True,
            )
        except RecipeRunException as exc:
            status = 502 if exc.error.stage == "data" else 422
            return self.json_response({"status": "error", **exc.error.model_dump()}, status=status)
        except Exception as exc:
            self.logger.exception("UISurfaces refresh failed")
            return self.json_response({"status": "error", "message": str(exc)}, status=500)

        envelope_dump = artifact.metadata.get("source_envelope")
        if envelope_dump is None:
            return self.json_response({"status": "error", "message": "Refresh did not produce an envelope"}, status=500)

        await self.store.update_envelope(surface_id, envelope_dump, merged_params)
        updated = await self.store.get(surface_id)
        accept = self.negotiation.negotiate(self.request)
        return await self.negotiation.respond(updated, accept)

    # ── POST: share mint ─────────────────────────────────────────────────

    async def _mint_share(self) -> web.Response:
        surface_id = self.request.match_info.get("surface_id")
        if not surface_id:
            return self._error("surface_id is required", status=400)
        user_id = await self._user_id()
        record = await self.store.get(surface_id)
        if record is None or record.user_id != user_id:
            return self._error("Surface not found", status=404)

        try:
            body = await self.request.json()
        except Exception:  # noqa: BLE001
            body = {}
        try:
            req = MintShareRequest.model_validate(body if isinstance(body, dict) else {})
        except ValidationError as exc:
            return self.json_response(
                {"status": "error", "message": "Invalid request", "errors": exc.errors()},
                status=400,
            )

        share = await self.store.mint_share(surface_id, expires_at=req.expires_at, use_default_ttl=req.ttl)
        return self.json_response(
            {
                "status": "success",
                "token": share.token,
                "expires_at": share.expires_at.isoformat() if share.expires_at else None,
                "permissions": share.permissions,
            },
            status=201,
        )

    # ── DELETE ───────────────────────────────────────────────────────────

    async def _delete_surface(self, surface_id: str | None) -> web.Response:
        if not surface_id:
            return self._error("surface_id is required", status=400)
        user_id = await self._user_id()
        deleted = await self.store.delete(surface_id, user_id or "")
        if not deleted:
            return self._error("Surface not found", status=404)
        return self.json_response({"status": "success"})

    async def _revoke_share(self, surface_id: str | None, token: str) -> web.Response:
        if not surface_id:
            return self._error("surface_id is required", status=400)
        user_id = await self._user_id()
        record = await self.store.get(surface_id)
        if record is None or record.user_id != user_id:
            return self._error("Surface not found", status=404)
        revoked = await self.store.revoke_share(token, surface_id)
        if not revoked:
            return self._error("Share token not found", status=404)
        return self.json_response({"status": "success"})
