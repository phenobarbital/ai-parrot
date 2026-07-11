"""A2UI deep-link web resume route (FEAT-273 Module 8, web channel).

Receives a deep-link click, consumes the single-use token via
:class:`~parrot.outputs.a2ui.deeplink.DeepLinkService`, and injects the action as a
**structured user message** into the original session through the AgentTalk POST flow.

The route is thin: token → ``consume()`` → structured message → resume invoker. Expired
or replayed tokens map to a friendly "session expired" response (no payload echo, no
stack trace). Registration is via :func:`setup_deeplink_routes` (call it wherever the
app registers ``AgentTalk``; the web resume path is ``/api/v1/a2ui/resume/web``).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

from aiohttp import web

from parrot.outputs.a2ui.deeplink import (
    DeepLinkExpiredError,
    DeepLinkService,
    ResumePayload,
)

logger = logging.getLogger(__name__)

#: An async callable that injects a resumed message into a session and returns a result.
#: Signature: (agent_name, query, session_id, user_id) -> Awaitable[Any].
ResumeInvoker = Callable[..., Awaitable[Any]]

_EXPIRED_MESSAGE = "This link has expired or was already used. Please request a new one."


def build_structured_message(payload: ResumePayload) -> str:
    """Serialize a resumed action into a structured user-message query string.

    The message is tagged so downstream can recognize it as an A2UI action resume
    rather than free-form user text.
    """
    return json.dumps(
        {"type": "a2ui_action_resume", "action": payload.action_payload},
        sort_keys=True,
    )


class DeepLinkResumeHandler:
    """Web resume handler for A2UI deep links."""

    def __init__(self, service: DeepLinkService, invoker: ResumeInvoker) -> None:
        self.service = service
        self.invoker = invoker
        self.logger = logging.getLogger(__name__)

    async def handle(self, token: str) -> tuple[dict[str, Any], int]:
        """Consume ``token`` and inject the action; return (body, http_status).

        Returns a friendly body + 410 on expired/replayed tokens.
        """
        if not token:
            return {"status": "error", "detail": "Missing token."}, 400
        try:
            payload = await self.service.consume(token)
        except DeepLinkExpiredError:
            self.logger.info("A2UI deep-link resume rejected (expired/replayed).")
            return {"status": "expired", "detail": _EXPIRED_MESSAGE}, 410

        query = build_structured_message(payload)
        result = await self.invoker(
            agent_name=payload.agent_id,
            query=query,
            session_id=payload.session_id,
            user_id=payload.user_id,
        )
        return {"status": "resumed", "session_id": payload.session_id, "result": result}, 200

    async def resume(self, request: web.Request) -> web.Response:
        """aiohttp entry point: read ``?token=`` and delegate to :meth:`handle`."""
        token = request.query.get("token", "")
        body, status = await self.handle(token)
        return web.json_response(body, status=status)


def setup_deeplink_routes(
    app: web.Application,
    service: DeepLinkService,
    invoker: ResumeInvoker,
    *,
    path: str = "/api/v1/a2ui/resume/web",
) -> DeepLinkResumeHandler:
    """Register the web resume route on ``app`` and return the handler.

    Call this alongside the ``AgentTalk`` registration. ``invoker`` should wrap the
    AgentTalk POST flow (``agent_name``/``query``/``session_id``/``user_id``).
    """
    handler = DeepLinkResumeHandler(service, invoker)
    app.router.add_get(path, handler.resume)
    logger.info("Registered A2UI deep-link web resume route at %s", path)
    return handler
