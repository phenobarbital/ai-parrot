"""Avatar session endpoint — start/stop an avatar session (FEAT-242 Phase A — Module 6).

Provides two REST endpoints for the LiveAvatar LITE avatar session:

    POST /api/v1/agents/avatar/{agent_id}/start
        Start an avatar session for the named agent.  Returns viewer credentials
        ONLY (``livekit_url``, ``client_token``, ``session_id``).  The
        ``agent_token`` and ``ws_url`` are NEVER returned to the client.

    POST /api/v1/agents/avatar/{agent_id}/stop
        Stop an active avatar session by ``session_id``.

The avatar mode flag (``avatar=true`` in the request body) wires an opt-in
hook that TASK-008 fills with per-tenant gating.

# TODO Q-deploy — spawn-per-session is used here; a warm pool of
#   AvatarSessionOrchestrator instances would reduce TTFB on the first request.
#   Owner: Jesús.  For now: one orchestrator per HTTP request, torn down on
#   completion.

Integration with ``AgentVoiceTalk``:
The avatar mode is exposed as a request flag (``avatar=true``) on the voice
endpoint.  A separate POST to ``/api/v1/agents/avatar/{agent_id}/start``
pre-starts the avatar session and returns viewer credentials that the browser
uses to join the LiveKit room; the browser still calls the voice endpoint as
normal for the actual dialogue.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from aiohttp import web
from navconfig.logging import logging

# Lazy imports so server boot never hard-requires the liveavatar stack.
# These are imported inside request handlers.


_logger = logging.getLogger("Parrot.AvatarSessionView")


async def _start_avatar_session(request: web.Request) -> web.Response:
    """POST /api/v1/agents/avatar/{agent_id}/start — start an avatar session.

    Reads LiveAvatar / LiveKit credentials from env, mints room tokens, creates
    a LiveAvatar LITE session (with livekit_config), and returns viewer
    credentials for the browser.

    Request body (JSON):
        session_id (str): AgentChat session ID (shared with the browser).
        tenant_id  (str, optional): Tenant identifier for opt-in gating.
        question   (str, optional): The first question to speak (may be empty).

    Response (JSON):
        livekit_url  (str): LiveKit WebSocket URL for the browser.
        client_token (str): Subscribe-only viewer JWT.
        session_id   (str): The shared session ID.

    The ``agent_token`` and ``ws_url`` are NEVER serialised here.

    # TODO Q-deploy — consider a warm pool of orchestrators if per-request
    #   startup latency proves too high on target hardware.
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
    )

    room_manager = LiveKitRoomManager()  # reads LIVEKIT_* from env

    # TODO Q-deploy: spawn-per-request is the simplest correct pattern.
    async with LiveAvatarClient(cfg) as client:
        # We do NOT run the full orchestrator here (no bot.ask_stream);
        # we just create the session + mint the viewer token and return.
        tokens = room_manager.mint_room_tokens(room=session_id, identity=agent_id)
        livekit_config: Dict[str, Any] = {
            "url": tokens.livekit_url,
            "room": tokens.room,
            "agentToken": tokens.agent_token,
        }
        handle = await client.create_session_token(cfg, livekit_config=livekit_config)
        await client.start_session(handle)

        _logger.info(
            "AvatarSessionView: started session %s for agent %s / tenant %s",
            session_id,
            agent_id,
            tenant_id,
        )

    # Return viewer credentials ONLY — agent_token and ws_url stay server-side.
    return web.json_response({
        "livekit_url": tokens.livekit_url,
        "client_token": tokens.client_token,
        "session_id": session_id,
    })


async def _stop_avatar_session(request: web.Request) -> web.Response:
    """POST /api/v1/agents/avatar/{agent_id}/stop — stop an active avatar session.

    Request body (JSON):
        session_id (str): The session to stop.

    Response: 204 No Content.
    """
    try:
        from parrot.integrations.liveavatar import LiveAvatarClient, LiveAvatarConfig
        from parrot.integrations.liveavatar.models import AvatarSessionHandle
    except ImportError as exc:
        raise web.HTTPServiceUnavailable(reason="LiveAvatar stack not installed") from exc

    try:
        body: Dict[str, Any] = await request.json()
    except Exception:  # noqa: BLE001
        body = {}

    session_id: str = body.get("session_id") or body.get("liveavatar_session_id") or ""
    session_token: str = body.get("session_token") or ""

    if not session_id:
        raise web.HTTPBadRequest(reason="'session_id' is required")

    api_key = os.environ.get("LIVEAVATAR_API_KEY", "")
    avatar_id = os.environ.get("LIVEAVATAR_AVATAR_ID", "")
    if not api_key or not avatar_id:
        raise web.HTTPServiceUnavailable(
            reason="LIVEAVATAR_API_KEY / LIVEAVATAR_AVATAR_ID env vars are not set"
        )

    cfg = LiveAvatarConfig(api_key=api_key, avatar_id=avatar_id)
    handle = AvatarSessionHandle(
        session_id=session_id,
        liveavatar_session_id=session_id,
        session_token=session_token,
        ws_url="",  # not needed for stop
        agent_name=avatar_id,
    )

    async with LiveAvatarClient(cfg) as client:
        await client.stop_session(handle)

    return web.Response(status=204)


def register_avatar_routes(router: Any) -> bool:
    """Register avatar session endpoints on the provided aiohttp router.

    Follows the same defensive-import pattern used by ``_register_voice_routes``
    in ``manager.py``.

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

    router.add_route("POST", "/api/v1/agents/avatar/{agent_id}/start", _start_avatar_session)
    router.add_route("POST", "/api/v1/agents/avatar/{agent_id}/stop", _stop_avatar_session)
    _logger.info("Avatar session routes registered.")
    return True
