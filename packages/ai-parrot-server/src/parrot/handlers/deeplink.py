"""A2UI deep-link web resume route (FEAT-273 Module 8, web channel; FEAT-469
TASK-2574 routes the resume through ``A2UIRuntime.dispatch``).

Receives a deep-link click, consumes the single-use token via
:class:`~parrot.outputs.a2ui.deeplink.DeepLinkService`, dispatches the already-
validated v1.0 ``action`` envelope through :class:`~parrot.outputs.a2ui.runtime.dispatch.A2UIRuntime`
(``transport="deeplink"``) so surface state persists exactly as the HTTP/A2A
paths do, and injects the action as a **structured user message** into the
original session through the AgentTalk POST flow (unchanged — the ``dispatch``
call and the invoker call are complementary, not alternatives: ``dispatch``
supplies surface-state persistence, the invoker supplies the conversational
turn).

The route is thin: token → ``consume()`` → dispatch → structured message →
resume invoker. Expired or replayed tokens map to a friendly "session
expired" response (no payload echo, no stack trace). Registration is via
:func:`setup_deeplink_routes` (call it wherever the app registers
``AgentTalk``; the web resume path is ``/api/v1/a2ui/resume/web``).
"""

from __future__ import annotations

import html
import json
import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from aiohttp import web

from parrot.outputs.a2ui.deeplink import (
    DeepLinkExpiredError,
    DeepLinkService,
    ResumePayload,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from parrot.outputs.a2ui.runtime.dispatch import A2UIRuntime

logger = logging.getLogger(__name__)

#: An async callable that injects a resumed message into a session and returns a result.
#: Signature: (agent_name, query, session_id, user_id) -> Awaitable[Any].
ResumeInvoker = Callable[..., Awaitable[Any]]

#: An async factory building the ``A2UIRuntime`` for a given ``(agent_id, user_id)``
#: (FEAT-469 TASK-2574). ``None`` (the default) skips the ``dispatch`` step
#: entirely — surface-state persistence is additive, never required for the
#: resume's core behaviour (turn injection via ``invoker`` still happens).
RuntimeFactory = Callable[[str, str], Awaitable["A2UIRuntime"]]

_EXPIRED_MESSAGE = "This link has expired or was already used. Please request a new one."

#: Confirm-before-consume landing page. GET renders this (NO state change); the button
#: POSTs to consume the single-use token. This prevents email/link prescanners
#: (Defender Safe Links, Google Workspace, …) — which GET every link before the user
#: clicks — from silently burning the token and presenting a false "expired" error.
_LANDING_HTML = (
    "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
    "<title>Resume</title><style>body{{font-family:sans-serif;margin:3rem;text-align:center}}"
    "button{{font-size:1.1rem;padding:.6rem 1.4rem;border-radius:8px;border:1px solid #3b7dd8;"
    "background:#3b7dd8;color:#fff;cursor:pointer}}</style></head><body>"
    "<h1>Continue your action</h1><p>Click below to resume in your original session.</p>"
    "<form method='post' action='?token={token}'><button type='submit'>Continue</button></form>"
    "</body></html>"
)


def build_structured_message(payload: ResumePayload) -> str:
    """Serialize a resumed action into a structured user-message query string.

    The message is tagged so downstream can recognize it as an A2UI action resume
    rather than free-form user text. Uses the same ``"a2ui_action"`` tag (and
    v1.0 ``action`` envelope shape, FEAT-470 G6) as the Adaptive Cards native-input
    submit path (``parrot.integrations.msteams.wrapper``, TASK-2545) so both ends
    of the pipe agree on one wire contract.
    """
    return json.dumps(
        {"type": "a2ui_action", "action": payload.action_payload},
        sort_keys=True,
    )


class DeepLinkResumeHandler:
    """Web resume handler for A2UI deep links.

    Args:
        service: Consumes the single-use token.
        invoker: Injects the structured turn into the session (AgentTalk POST flow).
        runtime_factory: Optional async factory building an
            :class:`~parrot.outputs.a2ui.runtime.dispatch.A2UIRuntime` for
            ``(agent_id, user_id)`` (FEAT-469 TASK-2574). When given,
            ``handle()`` dispatches the resumed ``action`` envelope through it
            (``transport="deeplink"``) BEFORE injecting the turn, so surface
            state persists exactly as the HTTP/A2A paths do. ``None`` (the
            default) skips this step — the resume still works, it just does
            not persist ``sendDataModel`` state.
    """

    def __init__(
        self,
        service: DeepLinkService,
        invoker: ResumeInvoker,
        runtime_factory: RuntimeFactory | None = None,
    ) -> None:
        self.service = service
        self.invoker = invoker
        self.runtime_factory = runtime_factory
        self.logger = logging.getLogger(__name__)

    async def handle(self, token: str) -> tuple[dict[str, Any], int]:
        """Consume ``token``, dispatch, and inject the action; return (body, http_status).

        Returns a friendly body + 410 on expired/replayed tokens.
        """
        if not token:
            return {"status": "error", "detail": "Missing token."}, 400
        try:
            payload = await self.service.consume(token)
        except DeepLinkExpiredError:
            self.logger.info("A2UI deep-link resume rejected (expired/replayed).")
            return {"status": "expired", "detail": _EXPIRED_MESSAGE}, 410

        if self.runtime_factory is not None:
            await self._dispatch(payload)

        query = build_structured_message(payload)
        result = await self.invoker(
            agent_name=payload.agent_id,
            query=query,
            session_id=payload.session_id,
            user_id=payload.user_id,
        )
        return {"status": "resumed", "session_id": payload.session_id, "result": result}, 200

    async def _dispatch(self, payload: ResumePayload) -> None:
        """Route the resumed ``action`` envelope through ``A2UIRuntime`` (spec §3 Module 7).

        ``payload.action_payload`` is already a validated v1.0 ``action``
        envelope (``ResumePayload``'s own ``field_validator``) — handed to
        ``dispatch`` directly, never re-wrapped or re-serialized. Errors here
        are logged, not raised: surface-state persistence is additive, and a
        failure must not block the (already-consumed, single-use) resume's
        turn injection.
        """
        from parrot.auth.permission import build_principal_context
        from parrot.outputs.a2ui.runtime.models import A2UICallContext

        try:
            runtime = await self.runtime_factory(payload.agent_id, payload.user_id)
            ctx = A2UICallContext(
                agent_id=payload.agent_id,
                user_id=payload.user_id,
                session_id=payload.session_id,
                transport="deeplink",
                permission_context=build_principal_context(principal=payload.user_id, channel=payload.channel),
            )
            await runtime.dispatch(payload.action_payload, ctx)
        except Exception:
            self.logger.exception("A2UI deep-link dispatch failed; continuing with turn injection only.")

    def render_landing(self, token: str) -> str:
        """Return the confirm-before-consume landing HTML (does NOT touch state)."""
        return _LANDING_HTML.format(token=html.escape(token, quote=True))

    async def landing(self, request: web.Request) -> web.Response:
        """GET entry point: render the confirm page WITHOUT consuming the token.

        Link prescanners GET this safely — the single-use token is only consumed by the
        POST from the user clicking the button.
        """
        token = request.query.get("token", "")
        return web.Response(text=self.render_landing(token), content_type="text/html")

    async def resume(self, request: web.Request) -> web.Response:
        """POST entry point: consume the token and inject the action."""
        token = request.query.get("token", "")
        body, status = await self.handle(token)
        return web.json_response(body, status=status)


def setup_deeplink_routes(
    app: web.Application,
    service: DeepLinkService,
    invoker: ResumeInvoker,
    *,
    path: str = "/api/v1/a2ui/resume/web",
    runtime_factory: RuntimeFactory | None = None,
) -> DeepLinkResumeHandler | None:
    """Register the web resume routes on ``app`` and return the handler.

    Registers ``GET`` (confirm landing, no consume) and ``POST`` (consume + inject) at the
    same path. Call this alongside the ``AgentTalk`` registration; ``invoker`` should wrap
    the AgentTalk POST flow (``agent_name``/``query``/``session_id``/``user_id``).

    Guards against double registration (spec §7: "cualquier despliegue que ya
    expusiera la ruta por otro medio podría duplicarla") — ``aiohttp`` raises
    on a duplicate route, which would crash app startup for such a
    deployment. If ``path`` is already registered, logs a warning and returns
    ``None`` instead of raising.

    Args:
        app: The aiohttp application.
        service: Consumes the single-use token.
        invoker: Injects the structured turn into the session.
        path: The web resume path.
        runtime_factory: Optional async ``(agent_id, user_id) -> A2UIRuntime``
            factory (FEAT-469 TASK-2574) — see :class:`DeepLinkResumeHandler`.

    Returns:
        The registered handler, or ``None`` if ``path`` was already mounted.
    """
    existing = {route.resource.canonical for route in app.router.routes() if route.resource is not None}
    if path in existing:
        logger.warning("A2UI deep-link web resume route %s is already registered; skipping.", path)
        return None

    handler = DeepLinkResumeHandler(service, invoker, runtime_factory=runtime_factory)
    app.router.add_get(path, handler.landing)  # confirm page — safe for prescanners
    app.router.add_post(path, handler.resume)  # consumes the single-use token
    logger.info("Registered A2UI deep-link web resume routes (GET landing + POST) at %s", path)
    return handler
