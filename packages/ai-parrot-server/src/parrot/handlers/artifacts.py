"""REST handler for artifact CRUD.

Provides endpoints for saving, loading, updating, and deleting
artifacts (charts, canvas tabs, infographics, dataframes, exports)
associated with a conversation thread.

FEAT-103: agent-artifact-persistency — Module 8.
FEAT-197: Added ArtifactPublicHTMLView and HTML content-negotiation.

Endpoints:
    GET    /api/v1/threads/{session_id}/artifacts               — list artifacts
    POST   /api/v1/threads/{session_id}/artifacts               — save artifact
    GET    /api/v1/threads/{session_id}/artifacts/{artifact_id}  — get artifact
    PUT    /api/v1/threads/{session_id}/artifacts/{artifact_id}  — update artifact
    DELETE /api/v1/threads/{session_id}/artifacts/{artifact_id}  — delete artifact

    GET    /api/v1/artifacts/public/{signature}/{artifact_id}.html  — public HTML
        (FEAT-197, TASK-1322)
        Signature scheme: ``{expiry}.{hmac_sha256}`` where
        ``hmac_sha256 = HMAC-SHA256(key=INFOGRAPHIC_SIGNING_KEY, msg='{artifact_id}|{expiry}')``
        base64url-encoded without padding.
        The env var INFOGRAPHIC_SIGNING_KEY is required for this endpoint to work.
        The env var INFOGRAPHIC_FRAME_ANCESTORS controls the CSP frame-ancestors
        directive (comma-separated, default ``'self'``).
"""
from __future__ import annotations

import re as _re
from typing import Optional
from datetime import datetime, timezone

from aiohttp import web
from navigator.views import BaseView
from navigator_session import get_session
from navigator_auth.decorators import is_authenticated, user_session
from navigator_auth.conf import AUTH_SESSION_OBJECT

from ..storage.models import Artifact, ArtifactType, ArtifactCreator
from ..storage.artifact_signing import (
    get_signing_key as _core_get_signing_key,
    sign_artifact as _core_sign_artifact,
    verify_signature as _core_verify_signature,
)
from .csp import build_csp_headers, frame_ancestors_from_env


# ---------------------------------------------------------------------------
# Signing helpers for FEAT-197 public artifact URL (design B)
#
# The signature scheme lives in ``parrot.storage.artifact_signing`` (core) so
# the producer (InfographicToolkit, which mints the signed URL at persist time)
# and the consumer (ArtifactPublicHTMLView below) agree byte-for-byte. The
# thin module-level wrappers preserve the historical private names used by
# tests and call sites in this module.
# ---------------------------------------------------------------------------

def _sign_artifact(artifact_id: str, expiry: int, key: bytes) -> str:
    """Compute HMAC-SHA256 over ``'{artifact_id}|{expiry}'`` (see core)."""
    return _core_sign_artifact(artifact_id, expiry, key)


def _verify_artifact_signature(artifact_id: str, signature_segment: str, key: bytes) -> bool:
    """Verify the ``{expiry}.{sig}`` signature segment (see core)."""
    return _core_verify_signature(artifact_id, signature_segment, key)


def _get_signing_key() -> bytes:
    """Read INFOGRAPHIC_SIGNING_KEY env var (see core).

    Returns bytes, or a deterministic fallback when the var is unset
    (not recommended for production; logged as a warning in the view).
    """
    return _core_get_signing_key()


@is_authenticated()
@user_session()
class ArtifactListView(BaseView):
    """List and create artifacts for a thread.

    GET  /api/v1/threads/{session_id}/artifacts      — list summaries
    POST /api/v1/threads/{session_id}/artifacts      — create artifact
    """

    _logger_name: str = "Parrot.ArtifactListView"

    def _get_artifact_store(self):
        """Retrieve ArtifactStore from the application context."""
        try:
            return self.request.app["artifact_store"]
        except KeyError:
            self.logger.error("artifact_store not found in app context")
            return None

    async def _get_user_id(self) -> Optional[str]:
        """Extract user_id from the authenticated session."""
        user = getattr(self.request, "user", None)
        if user:
            uid = getattr(user, "user_id", None) or getattr(user, "id", None)
            if uid:
                return str(uid)
        try:
            session = await get_session(self.request)
        except Exception:
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

    async def get(self) -> web.Response:
        """List all artifacts for a session as lightweight summaries.

        URL params:
            session_id: Conversation session identifier.
        Query params:
            agent_id (required): Agent/bot identifier.
        """
        store = self._get_artifact_store()
        if store is None:
            return self.error(
                response={"message": "Artifact store not available"},
                status=503,
            )

        user_id = await self._get_user_id()
        if not user_id:
            return self.error(
                response={"message": "User ID not found in session"},
                status=401,
            )

        session_id = self.request.match_info.get("session_id")
        if not session_id:
            return self.error(
                response={"message": "session_id is required in path"},
                status=400,
            )

        qs = self.get_arguments(self.request)
        agent_id = qs.get("agent_id", "")

        summaries = await store.list_artifacts(
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
        )

        return self.json_response({
            "artifacts": [s.model_dump(mode="json") for s in summaries],
            "count": len(summaries),
        })

    async def post(self) -> web.Response:
        """Save a new artifact.

        URL params:
            session_id: Conversation session identifier.
        Body:
            artifact_id (required): Unique artifact identifier.
            artifact_type (required): One of chart, canvas, infographic, dataframe, export.
            title (required): Display title.
            agent_id (required): Agent/bot identifier.
            definition (optional): Artifact definition dict.
            source_turn_id (optional): Turn that generated this artifact.
            created_by (optional): "user", "agent", or "system" (default "user").
        """
        store = self._get_artifact_store()
        if store is None:
            return self.error(
                response={"message": "Artifact store not available"},
                status=503,
            )

        user_id = await self._get_user_id()
        if not user_id:
            return self.error(
                response={"message": "User ID not found in session"},
                status=401,
            )

        session_id = self.request.match_info.get("session_id")
        if not session_id:
            return self.error(
                response={"message": "session_id is required in path"},
                status=400,
            )

        try:
            body = await self.json_data()
        except Exception:
            return self.error(
                response={"message": "Invalid JSON body"},
                status=400,
            )

        # Validate required fields
        artifact_id = body.get("artifact_id")
        artifact_type = body.get("artifact_type")
        title = body.get("title")
        agent_id = body.get("agent_id")

        if not all([artifact_id, artifact_type, title, agent_id]):
            return self.error(
                response={"message": "artifact_id, artifact_type, title, and agent_id are required"},
                status=400,
            )

        # Validate artifact_type
        try:
            a_type = ArtifactType(artifact_type)
        except ValueError:
            return self.error(
                response={"message": f"Invalid artifact_type: {artifact_type}"},
                status=400,
            )

        now = datetime.now(timezone.utc)
        artifact = Artifact(
            artifact_id=artifact_id,
            artifact_type=a_type,
            title=title,
            created_at=now,
            updated_at=now,
            source_turn_id=body.get("source_turn_id"),
            created_by=body.get("created_by", ArtifactCreator.USER),
            definition=body.get("definition"),
        )

        await store.save_artifact(
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
            artifact=artifact,
        )

        return self.json_response({
            "message": "Artifact saved",
            "artifact_id": artifact_id,
        }, status=201)


@is_authenticated()
@user_session()
class ArtifactDetailView(BaseView):
    """Detail operations on a single artifact.

    GET    /api/v1/threads/{session_id}/artifacts/{artifact_id}  — get
    PUT    /api/v1/threads/{session_id}/artifacts/{artifact_id}  — update
    DELETE /api/v1/threads/{session_id}/artifacts/{artifact_id}  — delete
    """

    _logger_name: str = "Parrot.ArtifactDetailView"

    def _get_artifact_store(self):
        """Retrieve ArtifactStore from the application context."""
        try:
            return self.request.app["artifact_store"]
        except KeyError:
            self.logger.error("artifact_store not found in app context")
            return None

    async def _get_user_id(self) -> Optional[str]:
        """Extract user_id from the authenticated session."""
        user = getattr(self.request, "user", None)
        if user:
            uid = getattr(user, "user_id", None) or getattr(user, "id", None)
            if uid:
                return str(uid)
        try:
            session = await get_session(self.request)
        except Exception:
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

    async def get(self) -> web.Response:
        """Get a single artifact with full definition resolved.

        URL params:
            session_id: Conversation session identifier.
            artifact_id: Artifact identifier.
        Query params:
            agent_id (required): Agent/bot identifier.
        """
        store = self._get_artifact_store()
        if store is None:
            return self.error(
                response={"message": "Artifact store not available"},
                status=503,
            )

        user_id = await self._get_user_id()
        if not user_id:
            return self.error(
                response={"message": "User ID not found in session"},
                status=401,
            )

        session_id = self.request.match_info.get("session_id")
        artifact_id = self.request.match_info.get("artifact_id")
        if not session_id or not artifact_id:
            return self.error(
                response={"message": "session_id and artifact_id are required"},
                status=400,
            )

        qs = self.get_arguments(self.request)
        agent_id = qs.get("agent_id", "")

        artifact = await store.get_artifact(
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
            artifact_id=artifact_id,
        )

        if artifact is None:
            return self.error(
                response={"message": f"Artifact {artifact_id} not found"},
                status=404,
            )

        # FEAT-197: Content-negotiation — return raw HTML when requested.
        accept = self.request.headers.get("Accept", "")
        fmt = self.request.query.get("format", "")
        if accept.startswith("text/html") or fmt == "html":
            html = _extract_html_from_artifact(artifact)
            raw_bundles = (artifact.definition or {}).get("js_bundles", [])
            try:
                from ..models.infographic import JSBundle
                bundles = [JSBundle.model_validate(b) if isinstance(b, dict) else b for b in raw_bundles]
            except Exception:
                bundles = []
            csp_headers = build_csp_headers(
                js_bundles=bundles,
                frame_ancestors=frame_ancestors_from_env(),
            )
            # ?download=1 → offer the self-contained HTML as a downloadable file
            # (the "open it and use it" delivery mode for interactive artifacts).
            if self.request.query.get("download") in ("1", "true", "yes"):
                safe_name = _re.sub(r"[^A-Za-z0-9._-]", "_", artifact_id) or "artifact"
                csp_headers = {
                    **dict(csp_headers),
                    "Content-Disposition": f'attachment; filename="{safe_name}.html"',
                }
            return web.Response(
                text=html,
                content_type="text/html",
                charset="utf-8",
                headers=csp_headers,
            )

        return self.json_response({
            "artifact": artifact.model_dump(mode="json"),
        })

    async def put(self) -> web.Response:
        """Update an artifact's definition.

        URL params:
            session_id: Conversation session identifier.
            artifact_id: Artifact identifier.
        Body:
            agent_id (required): Agent/bot identifier.
            definition (required): New definition dict.
        """
        store = self._get_artifact_store()
        if store is None:
            return self.error(
                response={"message": "Artifact store not available"},
                status=503,
            )

        user_id = await self._get_user_id()
        if not user_id:
            return self.error(
                response={"message": "User ID not found in session"},
                status=401,
            )

        session_id = self.request.match_info.get("session_id")
        artifact_id = self.request.match_info.get("artifact_id")
        if not session_id or not artifact_id:
            return self.error(
                response={"message": "session_id and artifact_id are required"},
                status=400,
            )

        try:
            body = await self.json_data()
        except Exception:
            return self.error(
                response={"message": "Invalid JSON body"},
                status=400,
            )

        agent_id = body.get("agent_id")
        definition = body.get("definition")
        if not agent_id or definition is None:
            return self.error(
                response={"message": "agent_id and definition are required"},
                status=400,
            )

        await store.update_artifact(
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
            artifact_id=artifact_id,
            definition=definition,
        )

        return self.json_response({
            "message": "Artifact updated",
            "artifact_id": artifact_id,
        })

    async def delete(self) -> web.Response:
        """Delete an artifact and clean up S3 data.

        URL params:
            session_id: Conversation session identifier.
            artifact_id: Artifact identifier.
        Query params:
            agent_id (required): Agent/bot identifier.
        """
        store = self._get_artifact_store()
        if store is None:
            return self.error(
                response={"message": "Artifact store not available"},
                status=503,
            )

        user_id = await self._get_user_id()
        if not user_id:
            return self.error(
                response={"message": "User ID not found in session"},
                status=401,
            )

        session_id = self.request.match_info.get("session_id")
        artifact_id = self.request.match_info.get("artifact_id")
        if not session_id or not artifact_id:
            return self.error(
                response={"message": "session_id and artifact_id are required"},
                status=400,
            )

        qs = self.get_arguments(self.request)
        agent_id = qs.get("agent_id", "")

        deleted = await store.delete_artifact(
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
            artifact_id=artifact_id,
        )

        if deleted:
            return self.json_response({
                "message": f"Artifact {artifact_id} deleted",
                "artifact_id": artifact_id,
            })
        return self.error(
            response={"message": f"Artifact {artifact_id} not found"},
            status=404,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_html_from_artifact(artifact: "Artifact") -> str:
    """Extract HTML from an artifact's definition.

    New artifacts (FEAT-197) always carry ``definition.html``.  Legacy
    artifacts saved by ``_auto_save_infographic_artifact`` may not have
    an ``html`` key — we fall back to re-rendering from the blocks envelope.

    Args:
        artifact: The resolved Artifact instance.

    Returns:
        HTML string (may be empty when neither source is available).
    """
    definition = artifact.definition or {}
    html = definition.get("html")
    if isinstance(html, str) and html:
        return html

    # Legacy fallback: re-render from blocks envelope
    blocks_envelope = definition.get("blocks_envelope")
    if blocks_envelope:
        try:
            from ..models.infographic import InfographicResponse
            from ..outputs.formats import get_infographic_html_renderer
            response = InfographicResponse.model_validate(blocks_envelope)
            theme = definition.get("theme")
            InfographicHTMLRenderer = get_infographic_html_renderer()
            return InfographicHTMLRenderer().render_to_html(response, theme=theme)
        except Exception:
            pass

    return ""


# ---------------------------------------------------------------------------
# FEAT-197 — Public artifact HTML endpoint (TASK-1322)
# ---------------------------------------------------------------------------


class ArtifactPublicHTMLView(web.View):
    """Public HTML serving endpoint for infographic artifacts.

    Design B (per TASK-1322): signature validated in-app, HTML streamed
    from ``Artifact.definition.html``; full CSP header set applied.

    Route:
        GET /api/v1/artifacts/public/{signature}/{artifact_id}.html

    Signature format:
        ``{expiry}.{hmac_sha256_base64url}``
        where
        ``hmac_sha256_base64url = HMAC-SHA256(INFOGRAPHIC_SIGNING_KEY,
                                               '{artifact_id}|{expiry}')``
        base64url-encoded without padding.

    Environment variables:
        INFOGRAPHIC_SIGNING_KEY:  Secret key for HMAC; required in prod.
        INFOGRAPHIC_FRAME_ANCESTORS: CSV of allowed frame ancestors; default 'self'.

    HTTP 403 on:
        - Invalid / tampered signature.
        - Expired signature (expiry < current UTC).
    """

    _logger_name: str = "Parrot.ArtifactPublicHTMLView"

    def __init__(self, *args, **kwargs) -> None:
        """Initialise the view with a standard logger."""
        import logging as _logging
        super().__init__(*args, **kwargs)
        self.logger = _logging.getLogger(self._logger_name)

    def _get_artifact_store(self):
        try:
            return self.request.app["artifact_store"]
        except KeyError:
            return None

    async def get(self) -> web.Response:
        """Serve the frozen infographic HTML for a valid signature."""
        signing_key = _get_signing_key()
        if signing_key == b"dev-insecure-key-change-in-prod":
            self.logger.warning(
                "INFOGRAPHIC_SIGNING_KEY env var not set — using insecure dev key. "
                "Set INFOGRAPHIC_SIGNING_KEY to a random 32+ byte secret before "
                "deploying to production."
            )

        signature = self.request.match_info.get("signature", "")
        # URL pattern: {artifact_id}.html — strip the .html suffix
        raw_artifact_id = self.request.match_info.get("artifact_id_html", "")
        artifact_id = raw_artifact_id.removesuffix(".html") if raw_artifact_id.endswith(".html") else raw_artifact_id

        if not _verify_artifact_signature(artifact_id, signature, signing_key):
            self.logger.warning(
                "Rejected public artifact request: invalid or expired signature "
                "for artifact_id=%s", artifact_id,
            )
            return web.Response(
                text="Forbidden: invalid or expired signature.",
                status=403,
                content_type="text/plain",
            )

        store = self._get_artifact_store()
        if store is None:
            return web.Response(
                text="Service unavailable: artifact store not configured.",
                status=503,
                content_type="text/plain",
            )

        # The public route does NOT have session context — we use the store's
        # scan capability.  For v1, the artifact_id itself is globally unique
        # (UUID-prefixed by the toolkit) so we can look it up without
        # user/agent/session scope by relying on the public scan API (if any)
        # or by using sentinels.  In this v1 implementation we look it up via
        # the scan path in the backend.  If the backend doesn't support a
        # global scan, we require the URL to carry agent/session params
        #
        # NOTE: The _public sentinel only works if the backend supports artifact
        # lookup by artifact_id alone. On scoped backends (DynamoDB, Redis), the
        # caller must supply user_id, agent_id, and session_id as query params.
        # Embedding these in the URL leaks session scope — use a GSI / secondary
        # index for production deployments that need public sharing without query
        # param leakage.
        # (documented limitation).
        qs = dict(self.request.query)
        agent_id = qs.get("agent_id", "")
        session_id = qs.get("session_id", "")
        user_id = qs.get("user_id", "")

        if not all([user_id, agent_id, session_id]):
            self.logger.warning(
                "Public artifact request for artifact_id=%s is missing scope params "
                "(user_id, agent_id, session_id). On scoped backends this will fall "
                "back to '_public' sentinels which may return 404 if unsupported. "
                "Pass scope params as query params for reliable lookup.",
                artifact_id,
            )

        # Try to fetch the artifact.  If the backend requires user/agent/session
        # context we need them; client may pass them as query params.
        try:
            artifact = await store.get_artifact(
                user_id=user_id or "_public",
                agent_id=agent_id or "_public",
                session_id=session_id or "_public",
                artifact_id=artifact_id,
            )
        except Exception as exc:
            self.logger.warning(
                "Error fetching artifact %s for public route: %s", artifact_id, exc,
            )
            artifact = None

        if artifact is None:
            return web.Response(
                text=f"Artifact {artifact_id!r} not found.",
                status=404,
                content_type="text/plain",
            )

        html = _extract_html_from_artifact(artifact)

        definition = artifact.definition or {}
        raw_bundles = definition.get("js_bundles", [])
        # Deserialise bundles if stored as dicts
        bundles: list = []
        if raw_bundles:
            try:
                from ..models.infographic import JSBundle
                for b in raw_bundles:
                    if isinstance(b, dict):
                        bundles.append(JSBundle.model_validate(b))
                    else:
                        bundles.append(b)
            except Exception:
                bundles = []

        csp_headers = build_csp_headers(
            js_bundles=bundles,
            frame_ancestors=frame_ancestors_from_env(),
        )

        self.logger.info(
            "Served public artifact id=%s size=%d bytes", artifact_id, len(html),
        )
        return web.Response(
            text=html,
            content_type="text/html",
            charset="utf-8",
            headers=csp_headers,
        )
