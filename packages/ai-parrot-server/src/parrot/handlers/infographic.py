"""HTTP handler for get_infographic() generation, plus template and theme
discovery/registration endpoints.

Routes (registered by BotManager in TASK-651):
    POST /api/v1/agents/infographic/{agent_id}          — generate infographic
    GET  /api/v1/agents/infographic/templates           — list templates
    GET  /api/v1/agents/infographic/templates/{name}    — get template
    POST /api/v1/agents/infographic/templates           — register template
    GET  /api/v1/agents/infographic/themes              — list themes
    GET  /api/v1/agents/infographic/themes/{name}       — get theme
    POST /api/v1/agents/infographic/themes              — register theme
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, Optional
from datetime import datetime, timezone

from aiohttp import web
from navconfig.logging import logging
from navigator_auth.decorators import is_authenticated, user_session
from navigator_session import get_session
from pydantic import ValidationError

from .agent import AgentTalk
from .infographic_render import (
    RenderBodyTooLargeError,
    RenderPayloadError,
    RenderRequest,
    RenderResponse,
    decode_inline_datasets,
    parse_multipart_render_request,
    render_deterministic,
)
from ..helpers.infographics import (
    get_template,
    get_theme,
    list_templates,
    list_themes,
    register_template,
    register_theme,
)
from ..tools.infographic_toolkit import InfographicToolkit, InfographicValidationError

# Keys consumed or reserved by the handler itself.  They must NOT be
# forwarded as ``**kwargs`` into ``bot.get_infographic`` because doing so
# either duplicates a named argument (TypeError) or leaks registration-only
# fields (``scope``) into the generation path.
_GENERATE_RESERVED_KEYS = frozenset({
    "query",
    "question",
    "template",
    "theme",
    "accept",
    "ctx",
    "user_id",
    "session_id",
    "use_vector_context",
    "use_conversation_history",
    "agent_name",
    "scope",
})


@is_authenticated()
@user_session()
class InfographicTalk(AgentTalk):
    """Dedicated HTTP handler for bot.get_infographic() plus template/theme
    discovery and registration endpoints.

    Inherits from AgentTalk to reuse authentication decorators, PBAC guards
    (``_check_pbac_agent_access``), agent lookup (``_get_agent``), and session
    management (``_get_user_session``).

    Content negotiation:
        Priority order — ``?format=`` query param > ``Accept`` header >
        default ``text/html``.
    """

    _logger_name: str = "Parrot.InfographicTalk"

    def post_init(self, *args, **kwargs) -> None:
        """Initialise logger for this handler.

        Logger level is intentionally left to the deployment-wide logging
        configuration — we do NOT force DEBUG here.
        """
        self.logger = logging.getLogger(self._logger_name)

    # ── Public HTTP verbs ──────────────────────────────────────────────

    async def post(self) -> web.Response:
        """Dispatch POST requests.

        Routing logic based on match_info:
            - ``resource == "templates"`` → register template
            - ``resource == "themes"``    → register theme
            - ``agent_id``                → generate infographic

        Returns:
            aiohttp web.Response with appropriate content type.
        """
        mi = self.request.match_info
        resource = mi.get("resource")
        if resource == "templates":
            return await self._handle_templates_register()
        if resource == "themes":
            return await self._handle_themes_register()
        if resource == "render":
            return await self._render_infographic_deterministic()
        # Default: per-agent infographic generation
        return await self._generate_infographic()

    async def get(self) -> web.Response:
        """Dispatch GET requests.

        Routing logic based on match_info:
            - ``resource == "templates"`` → list or get template
            - ``resource == "themes"``    → list or get theme
            - default                     → endpoint info

        Returns:
            aiohttp web.Response with JSON body.
        """
        mi = self.request.match_info
        resource = mi.get("resource")
        if resource == "templates":
            return await self._handle_templates_get(mi.get("template_name"))
        if resource == "themes":
            return await self._handle_themes_get(mi.get("theme_name"))
        return self.json_response({
            "message": "InfographicTalk — get_infographic HTTP handler",
            "version": "1.0",
            "endpoints": {
                "generate": "POST /api/v1/agents/infographic/{agent_id}",
                "list_templates": "GET /api/v1/agents/infographic/templates",
                "get_template": "GET /api/v1/agents/infographic/templates/{name}",
                "register_template": "POST /api/v1/agents/infographic/templates",
                "list_themes": "GET /api/v1/agents/infographic/themes",
                "get_theme": "GET /api/v1/agents/infographic/themes/{name}",
                "register_theme": "POST /api/v1/agents/infographic/themes",
            },
        })

    # ── Internal dispatchers ───────────────────────────────────────────

    async def _generate_infographic(self) -> web.Response:
        """Generate an infographic via bot.get_infographic().

        Reads the ``agent_id`` from the URL match_info, validates the request
        body (requires ``query``), resolves the agent and user session, then
        calls ``agent.get_infographic()`` with the negotiated accept type.

        Returns:
            - ``text/html`` response when ``accept == "text/html"``
            - JSON response wrapping the InfographicResponse when
              ``accept == "application/json"``
        """
        agent_id = self.request.match_info.get("agent_id")
        if not agent_id:
            return self.error("Missing agent_id in URL.", status=400)

        pbac_denied = await self._check_pbac_agent_access(
            agent_id=agent_id, action="agent:chat"
        )
        if pbac_denied is not None:
            return pbac_denied

        try:
            data = await self.request.json()
        except Exception:
            return self.error("Invalid JSON body.", status=400)
        if not isinstance(data, dict):
            return self.error(
                "Request body must be a JSON object.", status=400
            )

        query = data.pop("query", None)
        if not query or (isinstance(query, str) and not query.strip()):
            return self.error("Missing 'query' field in body.", status=400)

        agent = await self._get_agent(data)
        if isinstance(agent, web.Response):
            return agent

        user_id, session_id = await self._get_user_session(data)

        accept = self._negotiate_accept()

        template = data.pop("template", "basic")
        theme = data.pop("theme", None)
        use_vector_context = data.pop("use_vector_context", True)
        use_conversation_history = data.pop("use_conversation_history", False)

        # Build a whitelist of safe extra kwargs.  Anything reserved by the
        # handler or by ``get_infographic``'s named parameters is excluded to
        # avoid duplicate-keyword TypeErrors and to prevent registration-only
        # fields (e.g. ``scope``) from leaking into generation calls.
        extra_kwargs = {
            k: v for k, v in data.items() if k not in _GENERATE_RESERVED_KEYS
        }

        try:
            ai_message = await agent.get_infographic(
                question=query,
                template=template,
                theme=theme,
                accept=accept,
                session_id=session_id,
                user_id=user_id,
                use_vector_context=use_vector_context,
                use_conversation_history=use_conversation_history,
                ctx=None,
                **extra_kwargs,
            )
        except KeyError as exc:
            # Unknown template — registry raises KeyError
            return self.error(str(exc), status=404)
        except Exception as exc:
            self.logger.exception("Infographic generation failed: %s", exc)
            return self.error(f"Generation failed: {exc}", status=500)

        # --- FEAT-103: Auto-save infographic artifact (fire-and-forget) ---
        self._auto_save_infographic_artifact(
            ai_message, agent_id, user_id, session_id, template, theme,
        )

        if accept == "text/html":
            html = (
                getattr(ai_message, "content", None)
                or getattr(ai_message, "output", None)
                or ""
            )
            if not isinstance(html, str):
                html = str(html)
            # Explicit UTF-8 encoding — infographics routinely carry Unicode
            # (em-dashes, CSS unit glyphs, non-Latin data labels).
            return web.Response(
                body=html.encode("utf-8"),
                content_type="text/html",
                charset="utf-8",
            )

        # JSON path
        structured = getattr(ai_message, "structured_output", None) or getattr(
            ai_message, "output", None
        )
        if hasattr(structured, "model_dump"):
            payload = structured.model_dump()
        elif isinstance(structured, dict):
            payload = structured
        else:
            payload = {"output": str(structured)}
        return self.json_response({"infographic": payload})

    def _auto_save_infographic_artifact(
        self,
        ai_message: Any,
        agent_id: str,
        user_id: str,
        session_id: str,
        template: str,
        theme: Optional[str],
    ) -> None:
        """Fire-and-forget: persist the infographic as an artifact.

        Extracts the structured output from the AI message and saves it
        via ArtifactStore.  Failures are logged but never block the response.
        """
        artifact_store = self.request.app.get("artifact_store")
        if artifact_store is None:
            return

        structured = (
            getattr(ai_message, "structured_output", None)
            or getattr(ai_message, "output", None)
        )
        if structured is None:
            return

        if hasattr(structured, "model_dump"):
            definition = structured.model_dump()
        elif isinstance(structured, dict):
            definition = structured
        else:
            return

        try:
            from ..storage.models import (  # noqa: E501 pylint: disable=import-outside-toplevel
                Artifact,
                ArtifactType,
                ArtifactCreator,
            )
            now = datetime.now(timezone.utc)
            artifact_id = f"infog-{uuid.uuid4().hex[:8]}"
            artifact = Artifact(
                artifact_id=artifact_id,
                artifact_type=ArtifactType.INFOGRAPHIC,
                title=f"Infographic ({template})",
                created_at=now,
                updated_at=now,
                created_by=ArtifactCreator.AGENT,
                definition=definition,
            )
            asyncio.get_running_loop().create_task(
                artifact_store.save_artifact(
                    user_id=user_id,
                    agent_id=agent_id,
                    session_id=session_id,
                    artifact=artifact,
                )
            )
        except Exception as exc:
            self.logger.warning(
                "Auto-save infographic artifact failed: %s", exc
            )

    # ── Deterministic render (FEAT-327) ──────────────────────────────────

    async def _render_infographic_deterministic(self) -> web.Response:
        """Deterministic, bot-less render: ``POST .../infographic/render``.

        No ``{agent_id}``, no bot, no LLM. Decodes the request (JSON or
        multipart), runs the FEAT-326 validation gate via
        ``AdhocDatasetAdapter``, renders through a server-owned
        ``InfographicToolkit``, persists (awaited, unless ``persist=False``),
        and returns a negotiated response with the two-behavior URL rule.

        Returns:
            ``text/html`` (spliced/rendered HTML) or ``application/json``
            (``RenderResponse``), per ``_negotiate_accept()``. ``400`` on a
            malformed part/body, ``413`` over the body cap, ``404`` on an
            unknown template, ``422`` on aggregated validation deficits,
            ``501`` for ``async=true`` (TASK-1891 seam), ``5xx`` otherwise.
        """
        try:
            parsed, frames = await self._decode_render_request()
        except RenderPayloadError as exc:
            return self.json_response(
                {"error": "Malformed request", "part": exc.part_name, "detail": str(exc)},
                status=400,
            )
        except RenderBodyTooLargeError as exc:
            return self.json_response({"error": str(exc)}, status=413)
        except ValidationError as exc:
            return self.json_response(
                {"error": "Invalid RenderRequest", "details": exc.errors()}, status=400
            )

        if parsed.async_:
            # TASK-1891 seam: replace with Redis-backed job creation + 202.
            # NOTE: BaseView.error() only remaps a fixed status set (400/401/
            # 403/404/406/412/428) — 501 falls through to HTTPBadRequest, so
            # json_response() is used here to honor the real status code.
            return self.json_response(
                {"error": "async=true rendering is not yet implemented (TASK-1891)."},
                status=501,
            )

        try:
            get_template(parsed.template)
        except KeyError:
            return self.error(f"Unknown template '{parsed.template}'.", status=404)

        user_id, agent_id, session_id = await self._resolve_render_attribution(parsed)
        toolkit = self._get_render_toolkit()
        artifact_store = self.request.app.get("artifact_store") if parsed.persist else None
        if parsed.persist and artifact_store is None:
            self.logger.warning(
                "Render requested persist=True but app['artifact_store'] is not "
                "configured; proceeding WITHOUT persistence."
            )

        try:
            outcome = await render_deterministic(
                parsed,
                frames,
                toolkit=toolkit,
                artifact_store=artifact_store,
                user_id=user_id,
                agent_id=agent_id,
                session_id=session_id,
            )
        except InfographicValidationError as exc:
            if exc.code in ("sections_unmet", "payload_shape_mismatch"):
                return self.json_response(
                    {"error": exc.code, "detail": exc.detail}, status=422
                )
            self.logger.error("Render failed: %s — %s", exc.code, exc.detail)
            return self.json_response(
                {"error": exc.code, "detail": exc.detail}, status=500
            )
        except RenderPayloadError as exc:
            return self.json_response(
                {"error": "Payload assembly failed", "part": exc.part_name, "detail": str(exc)},
                status=400,
            )

        accept = self._negotiate_accept()
        if accept == "text/html":
            response = web.Response(
                body=outcome.html.encode("utf-8"),
                content_type="text/html",
                charset="utf-8",
            )
            response.headers["X-Artifact-Persisted"] = str(outcome.persisted).lower()
            return response

        payload = RenderResponse(
            artifact_id=outcome.artifact_id,
            url=outcome.url,
            template=parsed.template,
            sections_validated=outcome.sections_validated,
            persisted=outcome.persisted,
            timings=outcome.timings,
        )
        return self.json_response(payload.model_dump())

    async def _decode_render_request(self):
        """Decode the render body (JSON or multipart) into a ``RenderRequest`` + frames.

        Returns:
            Tuple of ``(RenderRequest, {name: DataFrame})`` — inline datasets
            decoded from the JSON body, plus (for multipart) the
            ``dataset:<name>`` parts.

        Raises:
            RenderPayloadError: Malformed body/part, or a declared ``None``
                dataset with no backing multipart part.
            RenderBodyTooLargeError: The body exceeds the configured cap.
            pydantic.ValidationError: The JSON body fails ``RenderRequest`` validation.
        """
        content_type = self.request.content_type or ""
        if content_type.startswith("multipart/"):
            reader = await self.request.multipart()
            parsed, multipart_frames = await parse_multipart_render_request(reader)
            frames = decode_inline_datasets(parsed)
            frames.update(multipart_frames)
            return parsed, frames

        try:
            body = await self.request.json()
        except Exception as exc:
            raise RenderPayloadError("request", f"invalid JSON body: {exc}") from exc
        parsed = RenderRequest.model_validate(body)
        frames = decode_inline_datasets(parsed)
        missing = [
            name for name, dataset in parsed.datasets.items()
            if dataset is None and name not in frames
        ]
        for name in missing:
            raise RenderPayloadError(
                f"dataset:{name}",
                "declared as null but the request is not multipart — no part to hydrate it",
            )
        return parsed, frames

    async def _resolve_render_attribution(self, parsed: RenderRequest):
        """Resolve ``(user_id, agent_id, session_id)`` attribution for a render.

        ``user_id`` comes ONLY from the authenticated session (never the
        body — the body cannot spoof another user's ownership); ``agent_id``/
        ``session_id`` come from the body, falling back to system defaults.

        Args:
            parsed: The parsed ``RenderRequest``.

        Returns:
            The resolved ``(user_id, agent_id, session_id)`` tuple.
        """
        user_id = None
        try:
            request_session = self.request.session or await get_session(self.request)
            if request_session:
                user_id = request_session.get("user_id")
        except AttributeError:
            pass
        user_id = user_id or "_anon"
        agent_id = parsed.agent_id or "_anon"
        session_id = parsed.session_id or uuid.uuid4().hex
        return str(user_id), str(agent_id), str(session_id)

    def _get_render_toolkit(self) -> InfographicToolkit:
        """Return (lazily building) the server-owned ``InfographicToolkit``.

        Cached on ``self.request.app["infographic_render_toolkit"]`` — ONE
        instance shared across requests. Safe to share: the render flow
        (``render_deterministic``) never mutates toolkit instance state
        (unlike the bot-bound authoring path), so there is no cross-request
        interference. ``template_dirs`` comes from the (new, minimal)
        ``app["infographic_render_template_dirs"]`` config key — mirrors the
        existing ``app["artifact_store"]`` DI convention
        (``manager.py`` on_startup). Absent config degrades to
        ``TEMPLATE_ENGINE_UNSET`` at render time rather than failing to build.
        """
        app = self.request.app
        toolkit = app.get("infographic_render_toolkit")
        if toolkit is None:
            toolkit = InfographicToolkit(
                artifact_store=app.get("artifact_store"),
                template_dirs=app.get("infographic_render_template_dirs"),
            )
            app["infographic_render_toolkit"] = toolkit
        return toolkit

    async def _handle_templates_get(
        self, name: Optional[str]
    ) -> web.Response:
        """Handle GET requests for templates.

        Args:
            name: Template name from URL, or None for list endpoint.

        Returns:
            JSON response with template list or single template details.
        """
        qs = self.query_parameters(self.request)
        if name is None:
            detailed = qs.get("detailed", "").lower() == "true"
            return self.json_response(
                {"templates": list_templates(detailed=detailed)}
            )
        try:
            tpl = get_template(name)
        except KeyError as exc:
            return self.error(str(exc), status=404)
        return self.json_response({"template": tpl.model_dump()})

    async def _handle_themes_get(
        self, name: Optional[str]
    ) -> web.Response:
        """Handle GET requests for themes.

        Args:
            name: Theme name from URL, or None for list endpoint.

        Returns:
            JSON response with theme list or single theme details.
        """
        qs = self.query_parameters(self.request)
        if name is None:
            detailed = qs.get("detailed", "").lower() == "true"
            return self.json_response(
                {"themes": list_themes(detailed=detailed)}
            )
        try:
            theme = get_theme(name)
        except KeyError as exc:
            return self.error(str(exc), status=404)
        return self.json_response({"theme": theme.model_dump()})

    async def _handle_templates_register(self) -> web.Response:
        """Handle POST requests to register a custom template.

        Requires ``agent:configure`` PBAC action. Session-scoped
        registration is not supported in v1 — returns 403.

        Returns:
            201 JSON response on success, 400 on validation error,
            403 on session scope or PBAC denial.
        """
        pbac_denied = await self._check_pbac_agent_access(
            agent_id="*", action="agent:configure"
        )
        if pbac_denied is not None:
            return pbac_denied

        try:
            data = await self.request.json()
        except Exception:
            return self.error("Invalid JSON body.", status=400)
        if not isinstance(data, dict):
            return self.error(
                "Request body must be a JSON object.", status=400
            )

        scope = (data.get("scope") or "global").lower()
        if scope == "session":
            return self.error(
                "Session-scoped template registration is not available in v1.",
                status=403,
            )

        payload = data.get("template")
        if not payload:
            return self.error("Missing 'template' field in body.", status=400)

        try:
            tpl = register_template(payload)
        except ValidationError as exc:
            return self.json_response(
                {"error": "Invalid template payload", "details": exc.errors()},
                status=400,
            )
        except TypeError as exc:
            return self.error(str(exc), status=400)
        return self.json_response(
            {"message": "Template registered", "template": tpl.model_dump()},
            status=201,
        )

    async def _handle_themes_register(self) -> web.Response:
        """Handle POST requests to register a custom theme.

        Requires ``agent:configure`` PBAC action. Session-scoped
        registration is not supported in v1 — returns 403.

        Returns:
            201 JSON response on success, 400 on validation error,
            403 on session scope or PBAC denial.
        """
        pbac_denied = await self._check_pbac_agent_access(
            agent_id="*", action="agent:configure"
        )
        if pbac_denied is not None:
            return pbac_denied

        try:
            data = await self.request.json()
        except Exception:
            return self.error("Invalid JSON body.", status=400)
        if not isinstance(data, dict):
            return self.error(
                "Request body must be a JSON object.", status=400
            )

        scope = (data.get("scope") or "global").lower()
        if scope == "session":
            return self.error(
                "Session-scoped theme registration is not available in v1.",
                status=403,
            )

        payload = data.get("theme")
        if not payload:
            return self.error("Missing 'theme' field in body.", status=400)

        try:
            theme = register_theme(payload)
        except ValidationError as exc:
            return self.json_response(
                {"error": "Invalid theme payload", "details": exc.errors()},
                status=400,
            )
        except TypeError as exc:
            return self.error(str(exc), status=400)
        return self.json_response(
            {"message": "Theme registered", "theme": theme.model_dump()},
            status=201,
        )

    # ── Helpers ────────────────────────────────────────────────────────

    def _negotiate_accept(self) -> str:
        """Resolve the desired content type for the response.

        Priority:
            1. Explicit ``?format=`` query parameter (``html`` or ``json``).
            2. ``Accept`` header containing ``application/json``.
            3. Default ``text/html``.

        Returns:
            ``"application/json"`` or ``"text/html"``.
        """
        qs = self.query_parameters(self.request)
        fmt = (qs.get("format") or "").lower()
        if fmt == "json":
            return "application/json"
        if fmt == "html":
            return "text/html"
        accept_header = self.request.headers.get("Accept", "")
        if "application/json" in accept_header:
            return "application/json"
        return "text/html"
