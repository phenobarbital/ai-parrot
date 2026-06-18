"""Avatar session endpoint — start/stop an avatar session (FEAT-242 Phase A — Module 6).

Provides two authenticated REST endpoints for the LiveAvatar LITE avatar session:

    POST /api/v1/agents/avatar/{agent_id}/start
        Start an avatar session for the named agent.  Returns viewer credentials
        ONLY (``livekit_url``, ``client_token``, ``session_id``).  The
        ``agent_token``, ``ws_url`` and ``session_token`` are NEVER returned to
        the client.  The live :class:`LiveAvatarClient` (with its keep-alive
        loop) is kept alive and stored in ``app['avatar_sessions']`` so the
        matching ``/stop`` can tear it down.

    POST /api/v1/agents/avatar/{agent_id}/stop
        Stop an active avatar session by ``session_id``: stops the LiveAvatar
        session, cancels the keep-alive loop, and closes the HTTP client.

Both endpoints are served through :class:`AvatarSessionView`, a
``navigator.views.BaseView`` decorated with ``@is_authenticated()`` and
``@user_session()`` (mirrors :class:`AgentTalk`) — so an unauthenticated caller
can neither start nor stop a session.

# TODO Q-deploy — spawn-per-session is used here; a warm pool of
#   AvatarSessionOrchestrator instances would reduce TTFB on the first request.
#   Owner: Jesús.

Integration with ``AgentVoiceTalk``:
The avatar mode is exposed as a request flag (``avatar=true``) on the voice
endpoint.  A separate POST to ``/api/v1/agents/avatar/{agent_id}/start``
pre-starts the avatar session and returns viewer credentials that the browser
uses to join the LiveKit room; the browser still calls the voice endpoint as
normal for the actual dialogue.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, Optional

from aiohttp import web
from navconfig.logging import logging
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session

# Lazy imports of the liveavatar stack happen inside the handlers so server
# boot never hard-requires the optional ``ai-parrot-integrations[liveavatar]``
# extra.

_logger = logging.getLogger("Parrot.AvatarSessionView")

# Key under which active avatar sessions are stored on the aiohttp Application.
# Maps session_id -> {"client": LiveAvatarClient, "handle": AvatarSessionHandle}.
AVATAR_SESSIONS_KEY = "avatar_sessions"


def _env_max_session_duration() -> Optional[int]:
    """Read the optional ``LIVEAVATAR_MAX_SESSION_DURATION`` env (seconds).

    Returns:
        The parsed integer, or ``None`` if unset/invalid.  Used as a safety-net
        backstop so abandoned sessions self-terminate server-side.
    """
    raw = os.environ.get("LIVEAVATAR_MAX_SESSION_DURATION", "")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        _logger.warning("Invalid LIVEAVATAR_MAX_SESSION_DURATION=%r; ignoring.", raw)
        return None


async def _start_avatar_session(request: web.Request) -> web.Response:
    """POST /api/v1/agents/avatar/{agent_id}/start — start an avatar session.

    Reads LiveAvatar / LiveKit credentials from env, mints room tokens, creates
    and starts a LiveAvatar LITE session (with ``livekit_config``), keeps the
    client alive in ``app['avatar_sessions']``, and returns viewer credentials.

    Request body (JSON):
        session_id (str): AgentChat session ID (shared with the browser).
        tenant_id  (str, optional): Tenant identifier for opt-in gating.

    Response (JSON):
        livekit_url  (str): LiveKit WebSocket URL for the browser.
        client_token (str): Subscribe-only viewer JWT.
        session_id   (str): The shared session ID.

    The ``agent_token``, ``ws_url`` and ``session_token`` are NEVER serialised.
    """
    try:
        from parrot.integrations.liveavatar import (
            LiveAvatarClient,
            LiveAvatarConfig,
            LiveKitRoomManager,
        )
        from parrot.integrations.liveavatar.optin import is_avatar_enabled
    except ImportError as exc:
        _logger.warning("LiveAvatar stack unavailable: %s", exc)
        raise web.HTTPServiceUnavailable(
            reason="LiveAvatar stack not installed"
        ) from exc

    agent_id = request.match_info["agent_id"]

    try:
        body: Dict[str, Any] = await request.json()
    except Exception:  # noqa: BLE001
        body = {}

    session_id: str = body.get("session_id") or ""
    tenant_id: Optional[str] = body.get("tenant_id") or None

    if not session_id:
        raise web.HTTPBadRequest(reason="'session_id' is required")

    # Per-tenant opt-in gate (wired by TASK-008)
    if not is_avatar_enabled(tenant_id=tenant_id, agent_name=agent_id):
        raise web.HTTPForbidden(reason="Avatar mode is not enabled for this tenant")

    # Build the config from env
    api_key = os.environ.get("LIVEAVATAR_API_KEY", "")
    avatar_id = os.environ.get("LIVEAVATAR_AVATAR_ID", "")
    if not api_key or not avatar_id:
        raise web.HTTPServiceUnavailable(
            reason="LIVEAVATAR_API_KEY / LIVEAVATAR_AVATAR_ID env vars are not set"
        )

    cfg = LiveAvatarConfig(
        api_key=api_key,
        avatar_id=avatar_id,
        base_url=os.environ.get("LIVEAVATAR_BASE_URL", "https://api.liveavatar.com"),
        is_sandbox=os.environ.get("LIVEAVATAR_SANDBOX", "true").lower() != "false",
        # Safety-net backstop so an abandoned session self-terminates even if
        # /stop is never called.
        max_session_duration=_env_max_session_duration(),
    )

    room_manager = LiveKitRoomManager()  # reads LIVEKIT_* from env

    # Mint viewer + agent tokens.  JWT signing is sync CPU work — keep it off
    # the event loop.
    tokens = await asyncio.to_thread(room_manager.mint_room_tokens, session_id, agent_id)
    livekit_config: Dict[str, Any] = {
        "url": tokens.livekit_url,
        "room": tokens.room,
        "agentToken": tokens.agent_token,
    }

    # Open the client and KEEP IT ALIVE — ownership transfers to the session
    # store; /stop tears it down.  We deliberately do NOT use ``async with``
    # here (that would call stop_session on block exit and kill the session
    # before the browser ever joins).
    client = LiveAvatarClient(cfg)
    await client.aopen()
    try:
        handle = await client.create_session_token(cfg, livekit_config=livekit_config)
        # create_session_token leaves session_id empty (it is the ai-parrot id,
        # unknown to the HTTP layer) — populate it now.
        handle.session_id = session_id
        handle.tenant_id = tenant_id
        await client.start_session(handle)
    except Exception:
        # On any failure, do not leak the client/session.
        try:
            await client.aclose()
        finally:
            pass
        raise

    # Register the live session so /stop (and shutdown cleanup) can reach it.
    store = request.app.setdefault(AVATAR_SESSIONS_KEY, {})
    store[session_id] = {"client": client, "handle": handle}

    _logger.info(
        "AvatarSessionView: started session %s for agent %s (tenant set=%s)",
        session_id,
        agent_id,
        tenant_id is not None,
    )

    # Return viewer credentials ONLY — agent_token / ws_url / session_token
    # stay server-side.
    return web.json_response({
        "livekit_url": tokens.livekit_url,
        "client_token": tokens.client_token,
        "session_id": session_id,
    })


async def _stop_avatar_session(request: web.Request) -> web.Response:
    """POST /api/v1/agents/avatar/{agent_id}/stop — stop an active avatar session.

    Identifies the session by ``session_id`` ONLY.  The ``session_token`` is a
    server-side secret and is never accepted from the client.

    Request body (JSON):
        session_id (str): The session to stop.

    Response: 204 No Content (idempotent — unknown/expired sessions also 204).
    """
    try:
        body: Dict[str, Any] = await request.json()
    except Exception:  # noqa: BLE001
        body = {}

    session_id: str = body.get("session_id") or ""
    if not session_id:
        raise web.HTTPBadRequest(reason="'session_id' is required")

    store: Dict[str, Any] = request.app.get(AVATAR_SESSIONS_KEY, {})
    record = store.pop(session_id, None)
    if not record:
        # Nothing to stop (already closed / unknown) — idempotent success.
        _logger.debug("AvatarSessionView: no active session for %s (idempotent)", session_id)
        return web.Response(status=204)

    client = record["client"]
    handle = record["handle"]
    try:
        await client.stop_session(handle)
    finally:
        # aclose cancels (and awaits) the keep-alive loop and closes the HTTP
        # session even if stop_session raised.
        await client.aclose()

    _logger.info("AvatarSessionView: stopped session %s", session_id)
    return web.Response(status=204)


@is_authenticated()
@user_session()
class AvatarSessionView(BaseView):
    """Authenticated entrypoint for the avatar start/stop actions.

    Routed at ``/api/v1/agents/avatar/{agent_id}/{action}`` where ``action`` is
    ``start`` or ``stop``.  Authentication/session decorators match
    :class:`AgentTalk`, so unauthenticated callers are rejected before any
    avatar session is created or destroyed.
    """

    async def post(self) -> web.Response:
        action = self.request.match_info.get("action", "")
        if action == "start":
            return await _start_avatar_session(self.request)
        if action == "stop":
            return await _stop_avatar_session(self.request)
        raise web.HTTPNotFound(reason=f"unknown avatar action '{action}'")


async def close_all_avatar_sessions(app: web.Application) -> None:
    """Best-effort teardown of any lingering avatar sessions on shutdown.

    Registered as an ``on_cleanup`` callback by the bot manager.  Iterates the
    session store, stops each LiveAvatar session and closes its client.
    """
    store: Dict[str, Any] = app.get(AVATAR_SESSIONS_KEY, {})
    for session_id, record in list(store.items()):
        client = record.get("client")
        handle = record.get("handle")
        try:
            if client is not None and handle is not None:
                await client.stop_session(handle)
        except Exception:  # noqa: BLE001
            _logger.warning("Failed stopping avatar session %s on shutdown", session_id, exc_info=True)
        finally:
            if client is not None:
                try:
                    await client.aclose()
                except Exception:  # noqa: BLE001
                    pass
    store.clear()


def register_avatar_routes(router: Any) -> bool:
    """Register avatar session endpoints on the provided aiohttp router.

    Follows the same defensive-import pattern used by ``_register_voice_routes``
    in ``manager.py``.  Routes are served through the authenticated
    :class:`AvatarSessionView`.

    Args:
        router: The aiohttp ``UrlDispatcher`` to register routes on.

    Returns:
        ``True`` if routes were registered, ``False`` if the stack is missing.
    """
    try:
        import parrot.integrations.liveavatar  # noqa: F401
    except ImportError as exc:
        _logger.warning(
            "Avatar endpoints disabled (%s); install "
            "'ai-parrot-integrations[liveavatar]' to enable "
            "POST /api/v1/agents/avatar/{agent_id}/start.",
            exc,
        )
        return False

    router.add_view(
        "/api/v1/agents/avatar/{agent_id}/{action}",
        AvatarSessionView,
    )
    _logger.info("Avatar session routes registered (authenticated).")
    return True
