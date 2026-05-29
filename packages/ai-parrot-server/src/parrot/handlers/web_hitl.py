"""Web HITL (Human-in-the-Loop) support for AI-Parrot.

This module provides:

1. **ContextVar helpers** — ``current_web_session`` stores the active WebSocket
   channel ID (typically the user's ``session_id``) so that tools invoked by an
   agent during a web request can resolve the correct recipient without being
   explicitly passed the value.

2. **WebHumanTool** — a :class:`~parrot.human.tool.HumanTool` subclass that
   lazily resolves the ``HumanInteractionManager`` and the target web session at
   invocation time, mirroring ``TelegramHumanTool``.

3. **HITLResponseBody / HITLResponseHandler** — a Pydantic model and an
   aiohttp :class:`~navigator.views.BaseView` that expose the
   ``POST /api/v1/agents/hitl/respond`` endpoint through which the frontend
   submits human answers back to the waiting agent.

4. **setup_web_hitl** — idempotent bootstrap function called from
   :class:`~parrot.manager.manager.BotManager` that ensures a process-wide
   :class:`~parrot.human.manager.HumanInteractionManager` and
   :class:`~parrot.human.channels.web.WebHumanChannel` are initialised at
   application startup.
"""
from __future__ import annotations

import json
import logging
from contextvars import ContextVar, Token
from typing import Any, List, Optional

from aiohttp import web
from pydantic import BaseModel, Field

from ..human import (
    HumanInteractionManager,
    HumanTool,
    WaitStrategy,
    get_default_human_manager,
    set_default_human_manager,
)
from ..human.channels.base import ESCALATE_OPTION_KEY
from ..human.models import HumanResponse, InteractionType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module 2a: ContextVar
# ---------------------------------------------------------------------------

#: Stores the active WebSocket channel name for the current request.
#: Set by :meth:`~parrot.handlers.agent.AgentTalk.post` at request entry
#: and reset in the ``finally`` block.
current_web_session: ContextVar[Optional[str]] = ContextVar(
    "current_web_session", default=None
)


def get_current_web_session() -> Optional[str]:
    """Return the active web session ID for the current request context.

    Returns:
        The WebSocket channel name previously set by
        :func:`set_current_web_session`, or ``None`` if none was set.
    """
    return current_web_session.get()


def set_current_web_session(session: Optional[str]) -> Token:
    """Set the active web session ID for the current request context.

    Args:
        session: WebSocket channel name (typically the user's ``session_id``
            or ``ws_channel_id``).

    Returns:
        A :class:`contextvars.Token` that can be used to restore the previous
        value via :func:`reset_current_web_session`.
    """
    return current_web_session.set(session)


def reset_current_web_session(token: Token) -> None:
    """Reset the web session ContextVar to its previous value.

    Should be called in a ``finally`` block to ensure the ContextVar is
    cleaned up even when the request handler raises an exception.

    Args:
        token: The :class:`contextvars.Token` returned by a prior call to
            :func:`set_current_web_session`.
    """
    current_web_session.reset(token)


# ---------------------------------------------------------------------------
# Module 2b: WebHumanTool
# ---------------------------------------------------------------------------


class WebHumanTool(HumanTool):
    """A :class:`~parrot.human.tool.HumanTool` that auto-resolves manager
    and target from the current web request context.

    Resolution order for the manager:
        1. ``self.manager`` if non-``None`` (set externally).
        2. :func:`~parrot.human.get_default_human_manager` (set by bootstrap).

    Resolution order for ``target_humans`` on each invocation:
        1. Explicit ``target_humans`` from the LLM call (``kwargs``).
        2. ``self.default_targets`` from construction.
        3. :func:`get_current_web_session` — the ContextVar set by
           :meth:`~parrot.handlers.agent.AgentTalk.post` at request entry.

    Args:
        default_targets: Fallback list of target human IDs.
        source_agent: Name of the agent that owns this tool (used to identify
            the source in the wire payload).
        **kwargs: Forwarded to :class:`~parrot.human.tool.HumanTool`.
    """

    def __init__(
        self,
        *,
        default_targets: Optional[List[str]] = None,
        source_agent: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            manager=None,
            default_channel="web",
            default_targets=default_targets or [],
            source_agent=source_agent,
            **kwargs,
        )
        self.logger = logging.getLogger(__name__)

    async def _execute(self, **kwargs: Any) -> Any:
        """Execute the tool with lazy manager and target resolution.

        Args:
            **kwargs: Tool input arguments forwarded from the LLM call.

        Returns:
            The consolidated human response value, or an error string.

        Raises:
            ValueError: When neither the ContextVar nor ``default_targets``
                provides a target and none was supplied in ``kwargs``.

        Note:
            This tool blocks the HTTP response for up to ``timeout`` seconds
            (default 7200s / 2h) while awaiting human input. For production
            use, this agent should be invoked via streaming or with a much
            shorter timeout. See docs/web-hitl-frontend-brainstorm.md.
        """
        # Lazy-resolve the manager
        if self.manager is None:
            self.manager = get_default_human_manager()
            if self.manager is not None:
                self.logger.info(
                    "WebHumanTool: resolved manager lazily from get_default_human_manager()"
                )

        if self.manager is None:
            return (
                "WebHumanTool error: no HumanInteractionManager configured. "
                "Ensure setup_web_hitl(app) has been called at startup."
            )

        # Pick the "web" channel if it exists; fall back to first available
        if "web" not in self.manager.channels and self.manager.channels:
            self.default_channel = next(iter(self.manager.channels))
            self.logger.warning(
                "WebHumanTool: 'web' channel not registered; falling back to '%s'.",
                self.default_channel,
            )

        # Auto-fill target_humans from the ContextVar when not supplied
        if not kwargs.get("target_humans") and not self.default_targets:
            session_id = get_current_web_session()
            if session_id:
                kwargs["target_humans"] = [session_id]
                self.logger.info(
                    "WebHumanTool: target_humans resolved from ContextVar: %s",
                    session_id,
                )
            else:
                self.logger.warning(
                    "WebHumanTool: ContextVar is empty and no default_targets set."
                )
                raise ValueError(
                    "WebHumanTool: cannot resolve target_humans — "
                    "current_web_session ContextVar is not set and no "
                    "default_targets were provided."
                )

        return await super()._execute(**kwargs)


# ---------------------------------------------------------------------------
# FEAT-204: SuspendingWebHumanTool (REST suspend/resume path)
# ---------------------------------------------------------------------------


class SuspendingWebHumanTool(WebHumanTool):
    """WebHumanTool variant wired for stateless REST suspend/resume (FEAT-204).

    Sets ``wait_strategy=WaitStrategy.SUSPEND``, which causes
    :meth:`~parrot.human.tool.HumanTool._execute` to call
    :meth:`~parrot.human.manager.HumanInteractionManager.request_human_input_async`
    and raise :class:`~parrot.core.exceptions.HumanInteractionInterrupt` instead of
    blocking.  The HTTP handler catches the interrupt, serialises the tool-loop
    state, and returns a ``paused`` envelope so the frontend can drive the
    resume flow via a later ``hitl_response``-tagged request.

    Lazy manager resolution and ``current_web_session``-based target resolution
    are fully inherited from :class:`WebHumanTool` — no re-implementation.

    Both :class:`WebHumanTool` (WebSocket long-poll, FEAT-146) and this class
    coexist.  Wire an agent with one or the other at construction:

    * Blocking (WebSocket): ``ask_human = WebHumanTool(source_agent=name)``
    * Stateless (REST):     ``ask_human = SuspendingWebHumanTool(source_agent=name)``

    Args:
        default_targets: Fallback list of target human IDs.
        source_agent: Name of the agent that owns this tool.
        **kwargs: Forwarded to :class:`WebHumanTool`.
    """

    def __init__(
        self,
        *,
        default_targets=None,
        source_agent=None,
        **kwargs,
    ) -> None:
        super().__init__(
            default_targets=default_targets,
            source_agent=source_agent,
            **kwargs,
        )
        # Override after super().__init__ — HumanTool.wait_strategy defaults to BLOCK.
        self.wait_strategy = WaitStrategy.SUSPEND


# ---------------------------------------------------------------------------
# Module 3: HITLResponseHandler
# ---------------------------------------------------------------------------


class HITLResponseBody(BaseModel):
    """Request body for ``POST /api/v1/agents/hitl/respond``.

    Attributes:
        interaction_id: UUID of the pending interaction to resolve.
        value: The human's response value (type depends on ``interaction_type``).
        response_type: Optional override for the response type. Defaults to the
            interaction's declared type.
    """

    interaction_id: str = Field(
        ...,
        description="UUID of the pending HITL interaction to resolve.",
    )
    value: Any = Field(
        ...,
        description="The human's response value.",
    )
    response_type: Optional[str] = Field(
        default=None,
        description="Response type override (optional).",
    )


try:
    from navigator.views import BaseView
    from navigator_auth.decorators import is_authenticated
    _NAV_AVAILABLE = True
except ImportError:
    # Fallback for testing environments without navigator installed
    BaseView = web.View  # type: ignore[assignment,misc]
    _NAV_AVAILABLE = False

    def is_authenticated():  # type: ignore[misc]
        """No-op decorator used when navigator_auth is not installed."""
        def decorator(func):
            return func
        return decorator

    logger.warning(
        "navigator_auth not installed: HITLResponseHandler is unauthenticated. "
        "This is only safe in test/dev environments."
    )


@is_authenticated()
class HITLResponseHandler(BaseView):
    """HTTP handler for ``POST /api/v1/agents/hitl/respond``.

    Accepts a JSON body containing ``interaction_id`` and ``value``, looks
    up the pending interaction in the default
    :class:`~parrot.human.manager.HumanInteractionManager`, and calls
    ``manager.receive_response(...)`` to unblock the waiting agent.

    Authentication:
        Requires a valid session (enforced by ``@is_authenticated()``).
        Respondent identity is taken from ``request.session.get('user_id')``.
    """

    async def post(self) -> web.Response:
        """Handle a human response submission.

        Returns:
            200 — ``{"ok": true, "interaction_id": "..."}`` on success.
            400 — ``{"error": "..."}`` on missing/invalid request body.
            404 — ``{"error": "interaction not found"}`` for unknown IDs.
            503 — ``{"error": "service unavailable"}`` when the manager is not
                  configured.
        """
        manager: Optional[HumanInteractionManager] = get_default_human_manager()
        if manager is None:
            logger.error(
                "HITLResponseHandler: no HumanInteractionManager configured."
            )
            return web.Response(
                status=503,
                content_type="application/json",
                body=json.dumps({"error": "HITL service unavailable"}),
            )

        # Parse and validate request body
        try:
            raw = await self.request.json()
        except Exception as exc:
            logger.warning("HITLResponseHandler: invalid JSON body — %s", exc)
            return web.Response(
                status=400,
                content_type="application/json",
                body=json.dumps({"error": f"Invalid JSON: {exc}"}),
            )

        try:
            body = HITLResponseBody(**raw)
        except Exception as exc:
            logger.warning(
                "HITLResponseHandler: body validation error — %s", exc
            )
            return web.Response(
                status=400,
                content_type="application/json",
                body=json.dumps({"error": str(exc)}),
            )

        interaction_id: str = body.interaction_id

        # Respondent identity from authenticated session, never from body
        respondent: str = "unknown"
        try:
            respondent = self.request.session.get("user_id", "unknown")
        except AttributeError:
            pass

        # Guard: reject unauthenticated callers before any further processing
        if respondent == "unknown":
            logger.warning(
                "HITLResponseHandler: unauthenticated request for interaction %s",
                interaction_id,
            )
            return web.Response(
                status=403,
                content_type="application/json",
                body=json.dumps({"error": "unauthenticated"}),
            )

        # Verify the interaction exists — if the manager has a pending future
        # for this ID the response is valid; if not, return 404.
        if (
            not manager.has_pending(interaction_id)
            and not await manager.get_result(interaction_id)
        ):
            logger.warning(
                "HITLResponseHandler: unknown interaction_id %s", interaction_id
            )
            return web.Response(
                status=404,
                content_type="application/json",
                body=json.dumps({"error": "interaction not found"}),
            )

        # Ownership check: only the intended respondent can submit a reply
        if not await manager.is_valid_respondent(interaction_id, respondent):
            logger.warning(
                "HITLResponseHandler: respondent '%s' is not authorised for "
                "interaction %s",
                respondent,
                interaction_id,
            )
            return web.Response(
                status=403,
                content_type="application/json",
                body=json.dumps({"error": "forbidden: not the intended respondent"}),
            )

        # Escalate path: web UI sends the sentinel value to trigger advance_chain.
        # Same auth gate as regular responses (is_valid_respondent already passed).
        if body.value == ESCALATE_OPTION_KEY:
            logger.info(
                "HITLResponseHandler: escalate request for interaction %s by %s",
                interaction_id,
                respondent,
            )
            try:
                await manager.advance_chain(interaction_id, cause="reject")
            except Exception as exc:
                logger.error(
                    "HITLResponseHandler: advance_chain failed for %s — %s",
                    interaction_id,
                    exc,
                )
                return web.Response(
                    status=500,
                    content_type="application/json",
                    body=json.dumps({"error": f"Failed to escalate: {exc}"}),
                )
            return web.Response(
                status=200,
                content_type="application/json",
                body=json.dumps({"status": "escalated", "interaction_id": interaction_id}),
            )

        # Determine response type
        response_type_str: str = (
            body.response_type or InteractionType.FREE_TEXT.value
        )
        try:
            response_type = InteractionType(response_type_str)
        except ValueError:
            response_type = InteractionType.FREE_TEXT

        response = HumanResponse(
            interaction_id=interaction_id,
            respondent=respondent,
            response_type=response_type,
            value=body.value,
        )

        try:
            await manager.receive_response(response)
        except Exception as exc:
            logger.error(
                "HITLResponseHandler: receive_response failed for %s — %s",
                interaction_id,
                exc,
            )
            return web.Response(
                status=500,
                content_type="application/json",
                body=json.dumps({"error": f"Failed to process response: {exc}"}),
            )

        logger.info(
            "HITLResponseHandler: resolved interaction %s for respondent %s",
            interaction_id,
            respondent,
        )
        return web.Response(
            status=200,
            content_type="application/json",
            body=json.dumps({"ok": True, "interaction_id": interaction_id}),
        )


# ---------------------------------------------------------------------------
# Module 4: Bootstrap
# ---------------------------------------------------------------------------


async def setup_web_hitl(app: web.Application) -> None:
    """Bootstrap a process-wide HumanInteractionManager with a WebHumanChannel.

    This coroutine is idempotent — it is safe to call multiple times. On each
    call it:

    1. Checks whether a manager already exists via
       :func:`~parrot.human.get_default_human_manager`.  If one exists,
       checks whether it already has a ``"web"`` channel registered; if so,
       skips entirely.
    2. If no manager exists, creates one backed by Redis
       (``parrot.conf.REDIS_URL``), registers a
       :class:`~parrot.human.channels.web.WebHumanChannel` under the name
       ``"web"``, calls :func:`~parrot.human.set_default_human_manager`, and
       awaits ``manager.startup()`` directly.
    3. If ``app['user_socket_manager']`` is absent, logs a WARNING but does
       not raise — the bootstrap completes with a degraded state where the
       web channel cannot deliver messages.

    This function awaits ``manager.startup()`` itself rather than appending a
    new ``on_startup`` hook, so it is safe to call from within an existing
    ``on_startup`` callback (where ``app.on_startup`` is frozen).

    Args:
        app: The :class:`aiohttp.web.Application` instance.
    """
    from ..human.channels.web import WebHumanChannel
    from ..conf import REDIS_URL

    manager = get_default_human_manager()
    socket_manager = app.get("user_socket_manager")

    if socket_manager is None:
        logger.warning(
            "setup_web_hitl: app['user_socket_manager'] is not set; "
            "WebHumanChannel will not be able to deliver messages. "
            "Ensure UserSocketManager is initialised before setup_web_hitl."
        )

    if manager is not None:
        # Manager already exists — check if "web" channel is registered
        if "web" in manager.channels:
            logger.debug(
                "setup_web_hitl: 'web' channel already registered; skipping."
            )
            return
        # Register the web channel on the existing manager
        if socket_manager is not None:
            channel = WebHumanChannel(socket_manager=socket_manager)
            manager.register_channel("web", channel)
            logger.info("setup_web_hitl: registered WebHumanChannel on existing manager.")
        return

    # No manager yet — create one and register the web channel
    new_manager = HumanInteractionManager(redis_url=REDIS_URL)

    if socket_manager is not None:
        channel = WebHumanChannel(socket_manager=socket_manager)
        new_manager.register_channel("web", channel)

    set_default_human_manager(new_manager)
    await new_manager.startup()
    logger.info(
        "setup_web_hitl: HumanInteractionManager created and started."
    )
