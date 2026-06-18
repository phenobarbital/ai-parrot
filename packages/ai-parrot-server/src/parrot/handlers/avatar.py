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

# Key under which active Phase C voice-native dispatches are stored (FEAT-243).
# Maps session_id -> {"room": str, "dispatch_id": str} so /stop (and shutdown
# cleanup) can delete the worker dispatch explicitly.
AVATAR_VOICE_SESSIONS_KEY = "avatar_voice_sessions"


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
    # Field names match LiveAvatar's LiveKitConfigSchema (snake_case).  The
    # avatar joins our room as a publisher, so it receives the publish-capable
    # ``agent_token`` (the subscribe-only client_token stays with the browser).
    livekit_config: Dict[str, Any] = {
        "livekit_url": tokens.livekit_url,
        "livekit_room": tokens.room,
        "livekit_client_token": tokens.agent_token,
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


async def _delete_voice_dispatch(record: Dict[str, Any]) -> None:
    """Best-effort delete of a Phase C voice-native worker dispatch.

    Called from :func:`_stop_avatar_session` and shutdown cleanup. Never raises —
    teardown must stay idempotent even if LiveKit is unreachable or the stack is
    missing.
    """
    room = record.get("room") or ""
    dispatch_id = record.get("dispatch_id") or ""
    if not room or not dispatch_id:
        return
    try:
        from parrot.integrations.liveavatar import LiveKitRoomManager

        room_manager = LiveKitRoomManager()
        await room_manager.delete_dispatch(room=room, dispatch_id=dispatch_id)
    except Exception:  # noqa: BLE001 - teardown must never raise
        _logger.warning(
            "Failed deleting voice-native dispatch %s (room %s)",
            dispatch_id,
            room,
            exc_info=True,
        )


async def _stop_avatar_session(request: web.Request) -> web.Response:
    """POST /api/v1/agents/avatar/{agent_id}/stop — stop an active avatar session.

    Identifies the session by ``session_id`` ONLY.  The ``session_token`` is a
    server-side secret and is never accepted from the client. Handles BOTH
    Phase A viewer sessions (a stored :class:`LiveAvatarClient`) and Phase C
    voice-native dispatches (a stored worker dispatch), keyed by the same
    ``session_id`` — the browser calls one ``/stop`` regardless of phase.

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

    # Phase C: delete the voice-native worker dispatch if one is tracked.
    voice_store: Dict[str, Any] = request.app.get(AVATAR_VOICE_SESSIONS_KEY, {})
    voice_record = voice_store.pop(session_id, None)
    if voice_record:
        await _delete_voice_dispatch(voice_record)
        _logger.info("AvatarSessionView: stopped voice-native session %s", session_id)

    # Phase A: tear down a stored viewer session if one exists.
    store: Dict[str, Any] = request.app.get(AVATAR_SESSIONS_KEY, {})
    record = store.pop(session_id, None)
    if not record:
        # Nothing more to stop (already closed / unknown) — idempotent success.
        if not voice_record:
            _logger.debug(
                "AvatarSessionView: no active session for %s (idempotent)", session_id
            )
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


def _worker_agent_name() -> str:
    """Read the LiveKit worker ``agent_name`` to dispatch (FEAT-243 Phase C).

    This is the LiveKit Agents worker's registered ``WorkerOptions(agent_name=...)``
    — NOT the ai-parrot brain agent (that travels in the job metadata). Defaults
    to ``"liveavatar-voice"`` (see ``examples/liveavatar_voice_worker.py``).
    """
    return os.environ.get("LIVEAVATAR_WORKER_AGENT_NAME", "liveavatar-voice")


async def _start_voice_native_session(request: web.Request) -> web.Response:
    """POST /api/v1/agents/avatar/{agent_id}/voice-native/start — Phase C (FEAT-243).

    Unlike the Phase A ``/start`` (which spawns a viewer-only avatar session),
    the voice-native flow lets the **browser publish its microphone** and hands
    turn-taking to a LiveKit Agents worker. This endpoint does the two things
    FEAT-243 left to the deployment:

    1. Mints a **publish-capable** browser token (``can_publish`` microphone +
       subscribe) — the Phase A ``client_token`` is subscribe-only and will not
       let the browser publish audio.
    2. **Explicitly dispatches** the worker into the room (= ``session_id``) with
       :class:`AvatarJobMetadata`, so the worker resolves the ai-parrot brain and
       speaks/streams structured outputs for this conversation.

    Request body (JSON):
        session_id (str): AgentChat session ID — names the LiveKit room AND the
            structured-output WS channel. Required.
        tenant_id  (str, optional): Tenant identifier for opt-in gating; also
            forwarded to the worker via the job metadata.

    Response (JSON):
        livekit_url (str): LiveKit WebSocket URL for the browser.
        token       (str): Publish(audio)+subscribe JWT for the browser.
        session_id  (str): The shared session ID.
    """
    try:
        from parrot.integrations.liveavatar import LiveKitRoomManager
        from parrot.integrations.liveavatar.livekit_agent.models import (
            AvatarJobMetadata,
        )
        from parrot.integrations.liveavatar.optin import is_avatar_enabled
    except ImportError as exc:
        _logger.warning("LiveAvatar voice stack unavailable: %s", exc)
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

    # Per-tenant opt-in gate (same gate as Phase A).
    if not is_avatar_enabled(tenant_id=tenant_id, agent_name=agent_id):
        raise web.HTTPForbidden(reason="Avatar mode is not enabled for this tenant")

    # LiveKitRoomManager() reads LIVEKIT_* from env and raises KeyError when a
    # required var is missing — surface that as 503 (env not provisioned).
    try:
        room_manager = LiveKitRoomManager()
    except KeyError as exc:
        raise web.HTTPServiceUnavailable(
            reason="LIVEKIT_* env vars are not set"
        ) from exc

    # Mint a publish-capable browser token. JWT signing is sync CPU work — keep
    # it off the event loop.
    token = await asyncio.to_thread(
        room_manager.mint_browser_token, session_id, agent_id
    )

    # Dispatch the worker into the room with the job metadata. ws_url is
    # informational for the worker (it connects via ctx.connect()).
    meta = AvatarJobMetadata(
        ws_url=room_manager.url,
        session_id=session_id,
        agent_name=agent_id,
        tenant_id=tenant_id,
    )
    try:
        dispatch_id = await room_manager.dispatch_worker(
            room=session_id,
            worker_agent_name=_worker_agent_name(),
            metadata_json=meta.model_dump_json(),
        )
    except Exception as exc:  # noqa: BLE001
        _logger.exception(
            "Voice-native dispatch failed for session %s (agent %s)",
            session_id,
            agent_id,
        )
        raise web.HTTPServiceUnavailable(
            reason="Failed to dispatch avatar voice worker"
        ) from exc

    # Track the dispatch so /stop (and shutdown cleanup) can delete it.
    voice_store = request.app.setdefault(AVATAR_VOICE_SESSIONS_KEY, {})
    voice_store[session_id] = {"room": session_id, "dispatch_id": dispatch_id}

    _logger.info(
        "AvatarSessionView: voice-native start session %s for agent %s "
        "(tenant set=%s)",
        session_id,
        agent_id,
        tenant_id is not None,
    )

    return web.json_response({
        "livekit_url": room_manager.url,
        "token": token,
        "session_id": session_id,
    })


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


@is_authenticated()
@user_session()
class VoiceNativeAvatarView(BaseView):
    """Authenticated entrypoint for the Phase C voice-native start (FEAT-243).

    Routed at ``/api/v1/agents/avatar/{agent_id}/voice-native/start``. Mints a
    publish-capable browser token and dispatches the LiveKit Agents worker into
    the room. Kept as a distinct view (not an ``{action}`` of
    :class:`AvatarSessionView`) because the path has a nested segment and the
    flow differs from Phase A.
    """

    async def post(self) -> web.Response:
        return await _start_voice_native_session(self.request)


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

    # Phase C: delete any lingering voice-native worker dispatches.
    voice_store: Dict[str, Any] = app.get(AVATAR_VOICE_SESSIONS_KEY, {})
    for session_id, record in list(voice_store.items()):
        await _delete_voice_dispatch(record)
    voice_store.clear()


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

    # Phase C voice-native start (FEAT-243) — registered BEFORE the generic
    # ``{action}`` route so the nested path is matched by its dedicated view.
    router.add_view(
        "/api/v1/agents/avatar/{agent_id}/voice-native/start",
        VoiceNativeAvatarView,
    )
    router.add_view(
        "/api/v1/agents/avatar/{agent_id}/{action}",
        AvatarSessionView,
    )
    _logger.info("Avatar session routes registered (authenticated).")
    return True
